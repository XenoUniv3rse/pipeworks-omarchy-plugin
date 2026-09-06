"""Mixing domain logic.

Holds the rules - what mute means when something else is soloed, which links a
routing table implies, what happens when a strip is added - and delegates every
side effect: audio operations to an AudioBackend, persistence to a
ConfigRepository, deferred work to an injected scheduler. That keeps this module
free of PipeWire, subprocess and GTK, and makes the rules testable with fakes.
"""
import time

from .. import settings
from . import effects as effects_module

CHANNEL = "channel"
INPUT = "input"
OUTPUT = "output"


class Mixer:
    def __init__(self, config, repository, backend, scheduler, filters=None):
        self.config = config
        self._repository = repository
        self._backend = backend
        self._schedule = scheduler
        # Effects are optional: without a filter host the mixer behaves exactly
        # as it did before they existed, which keeps tests free of PipeWire.
        self._filters = filters

        self.channels_by_id = {c["id"]: c for c in config["channels"]}
        self.inputs_by_id = {i["id"]: i for i in config["inputs"]}
        self.outputs_by_id = {o["id"]: o for o in config["outputs"]}

        # Observers, replaced by the UI and MIDI layers respectively.
        self.on_state_changed = lambda: None
        self.on_led = lambda kind, key, on: None

        self._volume_last_applied = {}
        self._volume_pending = set()

    # ------------------------------------------------------------------
    # Identity

    def loopback_output_names(self):
        """Node names of our own loopback outputs.

        These appear in the sink-input list exactly like application streams, so
        anything listing "what is playing" must exclude them.
        """
        names = {f"{chan['sink']}_out" for chan in self.config["channels"]}
        names.update(f"{inp['target_sink']}_out" for inp in self.config["inputs"])
        return names

    def strip_kind(self, strip_id):
        if strip_id in self.inputs_by_id:
            return INPUT
        if strip_id in self.outputs_by_id:
            return OUTPUT
        return CHANNEL

    def sink_for(self, strip_id):
        if strip_id in self.inputs_by_id:
            return self.inputs_by_id[strip_id]["target_sink"]
        return self.channels_by_id[strip_id]["sink"]

    def output_sink_for(self, out_id):
        return self.outputs_by_id[out_id]["port_l"].split(":")[0]

    def input_sources(self, inp):
        """The capture devices feeding one input, oldest first."""
        sources = inp.get("sources")
        return sources if isinstance(sources, list) else []

    def capture_ports_for_source(self, source):
        """Where one microphone's audio comes from.

        Tolerates entries written before ports were recorded - the original
        hardcoded mic predates them - by resolving from the device instead.
        """
        if source.get("capture_l") and source.get("capture_r"):
            return source["capture_l"], source["capture_r"]
        return self._backend.capture_ports(source["name"])

    def capture_ports_for_input(self, inp):
        """Every (left, right) pair feeding one input."""
        return [self.capture_ports_for_source(src) for src in self.input_sources(inp)]

    def effects_active(self, inp):
        """Whether this input's audio should travel through a filter chain."""
        return bool(self._filters) and bool(
            effects_module.enabled_effects(inp.get("effects"))
        )

    def input_destination(self, inp):
        """Where an input's microphones feed: its effects chain, or its sink.

        With effects on, the microphones play into the chain and the chain plays
        into the sink, so the strip's own fader still sits after everything.
        """
        if self.effects_active(inp):
            node = self._filters.input_node(inp["id"])
            return f"{node}:input_FL", f"{node}:input_FR"
        sink = inp["target_sink"]
        return f"{sink}:playback_FL", f"{sink}:playback_FR"

    def effects_tail_links(self, inp):
        """The links joining a chain's output to the strip's sink."""
        if not self.effects_active(inp):
            return []
        node = self._filters.output_node(inp["id"])
        sink = inp["target_sink"]
        return [
            (f"{node}:output_FL", f"{sink}:playback_FL"),
            (f"{node}:output_FR", f"{sink}:playback_FR"),
        ]

    def _unique_slug(self, label, fallback):
        base = "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_") or fallback
        taken = set(self.channels_by_id) | set(self.inputs_by_id) | set(self.outputs_by_id)
        slug = base
        suffix = 2
        while slug in taken:
            slug = f"{base}_{suffix}"
            suffix += 1
        return slug

    # ------------------------------------------------------------------
    # Adding and removing strips

    def add_channel(self, label):
        slug = self._unique_slug(label, "channel")
        channel = {"id": slug, "label": label, "sink": f"vchan_{slug}"}
        self.config["channels"].append(channel)
        self.channels_by_id[slug] = channel
        self.config["volume"][slug] = 70
        self.config["muted"][slug] = False
        self.config["solo"][slug] = False
        self.config["routes"][slug] = {oid: True for oid in self.outputs_by_id}
        self._reprovision()
        return slug

    def remove_channel(self, chan_id):
        self.config["channels"] = [c for c in self.config["channels"] if c["id"] != chan_id]
        self.channels_by_id.pop(chan_id, None)
        for store in ("volume", "muted", "solo", "routes"):
            self.config[store].pop(chan_id, None)
        for kind in ("volume_cc", "mute_note", "solo_note"):
            self.config["midi"][kind].pop(chan_id, None)
        self._forget_route_bindings(lambda key: key.startswith(f"{chan_id}:"))
        self._reprovision()

    def add_input(self, label, source_name):
        slug = self._unique_slug(label, "input")
        capture_l, capture_r = self._backend.capture_ports(source_name)
        self.config["inputs"].append(
            {
                "id": slug,
                "label": label,
                "target_sink": f"virtual_{slug}",
                "sources": [
                    {
                        "name": source_name,
                        "volume": 100,
                        "capture_l": capture_l,
                        "capture_r": capture_r,
                    }
                ],
            }
        )
        self.inputs_by_id[slug] = self.config["inputs"][-1]
        self.config["volume"][slug] = 70
        self.config["muted"][slug] = False
        self._reprovision()
        return slug

    def remove_input(self, input_id):
        # Stop and forget its effects chain, or a host process outlives the
        # strip it belonged to and its config file is left behind.
        if self._filters:
            self._filters.forget(input_id)
        self.config["inputs"] = [i for i in self.config["inputs"] if i["id"] != input_id]
        self.inputs_by_id.pop(input_id, None)
        for store in ("volume", "muted"):
            self.config[store].pop(input_id, None)
        for kind in ("volume_cc", "mute_note"):
            self.config["midi"][kind].pop(input_id, None)
        self._reprovision()

    def add_output(self, label, sink_name):
        """Adds a physical output bus.

        Needs no reprovisioning: unlike channels and inputs, an output is only a
        link destination on hardware that already exists.
        """
        slug = self._unique_slug(label, "output")
        port_l, port_r = self._backend.playback_ports(sink_name)
        output = {"id": slug, "label": label, "port_l": port_l, "port_r": port_r}
        self.config["outputs"].append(output)
        self.outputs_by_id[slug] = output
        self.config["output_volume"][slug] = 100
        self.config["output_muted"][slug] = False
        self.config["output_solo"][slug] = False
        for chan in self.config["channels"]:
            self.config["routes"][chan["id"]][slug] = True

        self._repository.save(self.config)
        self.apply_all()
        return slug

    def remove_output(self, out_id):
        output = self.outputs_by_id[out_id]
        for chan in self.config["channels"]:
            if self.config["routes"][chan["id"]].get(out_id):
                self._backend.disconnect(f"{chan['sink']}_out:output_FL", output["port_l"])
                self._backend.disconnect(f"{chan['sink']}_out:output_FR", output["port_r"])

        self.config["outputs"] = [o for o in self.config["outputs"] if o["id"] != out_id]
        self.outputs_by_id.pop(out_id, None)
        for store in ("output_volume", "output_muted", "output_solo"):
            self.config[store].pop(out_id, None)
        for routes in self.config["routes"].values():
            routes.pop(out_id, None)
        for kind in ("output_volume_cc", "output_mute_note", "output_solo_note"):
            self.config["midi"][kind].pop(out_id, None)
        self._forget_route_bindings(lambda key: key.endswith(f":{out_id}"))

        self._repository.save(self.config)
        self.apply_all()

    def retarget_output(self, out_id, sink_name):
        """Points an existing output bus at a different device."""
        output = self.outputs_by_id[out_id]
        # Unhook every channel from the old device first, or it keeps playing
        # alongside the new one.
        for chan in self.config["channels"]:
            if self.config["routes"][chan["id"]].get(out_id):
                self._backend.disconnect(f"{chan['sink']}_out:output_FL", output["port_l"])
                self._backend.disconnect(f"{chan['sink']}_out:output_FR", output["port_r"])

        output["port_l"], output["port_r"] = self._backend.playback_ports(sink_name)
        self._repository.save(self.config)
        self.apply_all()

    def retarget_input(self, input_id, source_name):
        """Swaps an input's first capture device for another.

        Kept for callers that predate an input having a list of them; the
        window adds and removes sources individually instead.
        """
        inp = self.inputs_by_id[input_id]
        sources = self.input_sources(inp)
        if not sources:
            self.add_input_source(input_id, source_name)
            return
        self._unlink_source(inp, sources[0])
        sources[0]["name"] = source_name
        sources[0]["capture_l"], sources[0]["capture_r"] = self._backend.capture_ports(
            source_name
        )
        self._repository.save(self.config)
        self.apply_all()

    # ------------------------------------------------------------------
    # An input's microphones
    #
    # Every source is linked into the same virtual sink and PipeWire sums them,
    # so adding one is only extra links on hardware that already exists - no
    # reprovisioning, and no break in audio, unlike adding a whole input.

    def add_input_source(self, input_id, source_name):
        inp = self.inputs_by_id[input_id]
        sources = self.input_sources(inp)
        if any(src.get("name") == source_name for src in sources):
            return  # already feeding this input
        capture_l, capture_r = self._backend.capture_ports(source_name)
        sources.append(
            {
                "name": source_name,
                "volume": 100,
                "capture_l": capture_l,
                "capture_r": capture_r,
            }
        )
        inp["sources"] = sources
        self._repository.save(self.config)
        self.apply_all()

    def remove_input_source(self, input_id, source_name):
        inp = self.inputs_by_id[input_id]
        remaining = []
        for source in self.input_sources(inp):
            if source.get("name") == source_name:
                # Unhook it first: leaving the link in place keeps the
                # microphone live in a strip that no longer lists it.
                self._unlink_source(inp, source)
            else:
                remaining.append(source)
        inp["sources"] = remaining
        self._repository.save(self.config)
        self.apply_all()

    # ------------------------------------------------------------------
    # Effects

    def set_effect_enabled(self, strip_id, effect_id, enabled):
        """Switches one effect on or off.

        This rebuilds the graph, which only takes effect when the chain host
        restarts - so unlike moving a control, it briefly interrupts this strip.
        """
        if effect_id not in effects_module.EFFECTS_BY_ID:
            return
        inp = self.inputs_by_id.get(strip_id)
        if not inp:
            return
        stored = inp.setdefault("effects", {})
        entry = stored.setdefault(effect_id, {"enabled": False, "controls": {}})
        if bool(entry.get("enabled")) == bool(enabled):
            return
        entry["enabled"] = bool(enabled)
        entry.setdefault("controls", {})
        # Seed the controls so a front end has values to show immediately.
        for control_id, value in effects_module.default_controls(effect_id).items():
            entry["controls"].setdefault(control_id, value)

        self._rewire_input(inp)
        self._repository.save(self.config)
        self.apply_all()
        self.on_state_changed()

    def set_effect_control(self, strip_id, effect_id, control_id, value):
        """Moves one control on a running chain. No restart, no interruption."""
        spec = effects_module.control_spec(effect_id, control_id)
        inp = self.inputs_by_id.get(strip_id)
        if not spec or not inp:
            return
        entry = inp.setdefault("effects", {}).setdefault(
            effect_id, {"enabled": False, "controls": {}}
        )
        clamped = max(spec["minimum"], min(spec["maximum"], float(value)))
        entry.setdefault("controls", {})[control_id] = clamped

        if self.effects_active(inp):
            self._filters.set_control(
                strip_id,
                effects_module.port_name(spec),
                effects_module.plugin_value(spec, clamped),
            )
        self._throttled(
            ("effect", strip_id, effect_id, control_id),
            lambda: self._repository.save(self.config),
        )
        self.on_state_changed()

    def set_input_source_volume(self, input_id, source_name, percent):
        inp = self.inputs_by_id[input_id]
        for source in self.input_sources(inp):
            if source.get("name") == source_name:
                source["volume"] = percent
                self._backend.set_source_volume(source_name, percent)
                self._throttled(
                    ("input_source", input_id, source_name),
                    lambda: self._repository.save(self.config),
                )
                self.on_state_changed()
                return

    def _unlink_source(self, inp, source):
        capture_l, capture_r = self.capture_ports_for_source(source)
        # Both possible destinations: whether effects were on when this link was
        # made is not worth tracking, and disconnecting a link that was never
        # there is harmless.
        for dest_l, dest_r in self._possible_destinations(inp):
            self._backend.disconnect(capture_l, dest_l)
            self._backend.disconnect(capture_r, dest_r)

    def _possible_destinations(self, inp):
        sink = inp["target_sink"]
        destinations = [(f"{sink}:playback_FL", f"{sink}:playback_FR")]
        if self._filters:
            node = self._filters.input_node(inp["id"])
            destinations.append((f"{node}:input_FL", f"{node}:input_FR"))
        return destinations

    def _rewire_input(self, inp):
        """Tears an input's links down so apply_all can rebuild them.

        Turning effects on or off moves where every microphone points, and a
        stale link left behind would keep the old path live alongside the new
        one - both audible at once.
        """
        for source in self.input_sources(inp):
            self._unlink_source(inp, source)
        if self._filters:
            node = self._filters.output_node(inp["id"])
            sink = inp["target_sink"]
            self._backend.disconnect(f"{node}:output_FL", f"{sink}:playback_FL")
            self._backend.disconnect(f"{node}:output_FR", f"{sink}:playback_FR")

    def rename(self, entity, label):
        entity["label"] = label
        self._repository.save(self.config)

    def _forget_route_bindings(self, matches):
        self.config["midi"]["route_note"] = {
            key: note
            for key, note in self.config["midi"]["route_note"].items()
            if not matches(key)
        }

    def _reprovision(self):
        self._repository.save(self.config)
        self._backend.provision(self.config["channels"], self.config["inputs"])
        self.apply_all()

    # ------------------------------------------------------------------
    # Volume

    @property
    def volume_locked(self):
        """Whether levels are reserved to the control surface."""
        return bool(self.config.get("volume_locked", False))

    def set_volume_locked(self, locked):
        self.config["volume_locked"] = bool(locked)
        self._repository.save(self.config)
        self.on_state_changed()

    def set_volume(self, strip_id, percent, from_surface=False):
        """Sets a strip's level.

        from_surface marks a change as coming from the control surface, which is
        the one source the lock never blocks - the point of locking is to stop
        software from moving levels out from under the physical faders.
        """
        if self.volume_locked and not from_surface:
            # Re-notify so a UI that moved its own slider snaps back.
            self.on_state_changed()
            return
        percent = max(0, min(100, percent))
        self.config["volume"][strip_id] = percent
        self.on_state_changed()
        self._throttled(f"strip:{strip_id}", lambda: self._apply_volume(strip_id))

    def set_output_volume(self, out_id, percent, from_surface=False):
        if self.volume_locked and not from_surface:
            self.on_state_changed()
            return
        percent = max(0, min(100, percent))
        self.config["output_volume"][out_id] = percent
        self.on_state_changed()
        self._throttled(f"output:{out_id}", lambda: self._apply_output_volume(out_id))

    def _apply_volume(self, strip_id):
        self._backend.set_sink_volume(self.sink_for(strip_id), self.config["volume"][strip_id])
        self._repository.save(self.config)

    def _apply_output_volume(self, out_id):
        self._backend.set_sink_volume(
            self.output_sink_for(out_id), self.config["output_volume"][out_id]
        )
        self._repository.save(self.config)

    def _throttled(self, key, apply_fn):
        """Coalesces rapid updates to at most one write per throttle interval.

        The caller has already updated in-memory state and notified observers,
        so dropping intermediate values is safe; what matters is that the last
        value always lands.
        """
        now = time.monotonic()
        last = self._volume_last_applied.get(key, 0)
        if now - last >= settings.VOLUME_THROTTLE_SECONDS:
            self._volume_last_applied[key] = now
            apply_fn()
            return

        if key in self._volume_pending:
            return

        def fire():
            self._volume_pending.discard(key)
            self._volume_last_applied[key] = time.monotonic()
            apply_fn()

        self._volume_pending.add(key)
        delay_ms = int((settings.VOLUME_THROTTLE_SECONDS - (now - last)) * 1000)
        self._schedule(max(delay_ms, 1), fire)

    # ------------------------------------------------------------------
    # Mute and solo

    def _effective_mute(self, strip_id):
        # Inputs sit outside the channel solo group: soloing a playback channel
        # should not cut your microphone.
        if strip_id in self.inputs_by_id:
            return self.config["muted"][strip_id]
        any_solo = any(self.config["solo"].values())
        muted = self.config["muted"][strip_id]
        soloed = self.config["solo"].get(strip_id, False)
        return muted or (any_solo and not soloed)

    def _apply_mute(self, strip_id):
        self._backend.set_sink_mute(self.sink_for(strip_id), self._effective_mute(strip_id))

    def set_mute(self, strip_id, value):
        self.config["muted"][strip_id] = value
        self._apply_mute(strip_id)
        self._repository.save(self.config)
        self.on_led("mute", strip_id, value)
        self.on_state_changed()

    def toggle_mute(self, strip_id):
        self.set_mute(strip_id, not self.config["muted"][strip_id])

    def set_solo(self, strip_id, value):
        self.config["solo"][strip_id] = value
        for chan in self.config["channels"]:
            self._apply_mute(chan["id"])
        self._repository.save(self.config)
        self.on_led("solo", strip_id, value)
        self.on_state_changed()

    def toggle_solo(self, strip_id):
        self.set_solo(strip_id, not self.config["solo"][strip_id])

    def _effective_output_mute(self, out_id):
        any_solo = any(self.config["output_solo"].values())
        muted = self.config["output_muted"][out_id]
        soloed = self.config["output_solo"][out_id]
        return muted or (any_solo and not soloed)

    def _apply_output_mute(self, out_id):
        self._backend.set_sink_mute(
            self.output_sink_for(out_id), self._effective_output_mute(out_id)
        )

    def set_output_mute(self, out_id, value):
        self.config["output_muted"][out_id] = value
        self._apply_output_mute(out_id)
        self._repository.save(self.config)
        self.on_led("output_mute", out_id, value)
        self.on_state_changed()

    def toggle_output_mute(self, out_id):
        self.set_output_mute(out_id, not self.config["output_muted"][out_id])

    def set_output_solo(self, out_id, value):
        self.config["output_solo"][out_id] = value
        for oid in self.outputs_by_id:
            self._apply_output_mute(oid)
        self._repository.save(self.config)
        self.on_led("output_solo", out_id, value)
        self.on_state_changed()

    def toggle_output_solo(self, out_id):
        self.set_output_solo(out_id, not self.config["output_solo"][out_id])

    # ------------------------------------------------------------------
    # Routing

    def set_route(self, chan_id, out_id, value):
        self.config["routes"][chan_id][out_id] = value
        self._apply_route(chan_id, out_id)
        self._repository.save(self.config)
        self.on_led("route", f"{chan_id}:{out_id}", value)
        self.on_state_changed()

    def toggle_route(self, chan_id, out_id):
        self.set_route(chan_id, out_id, not self.config["routes"][chan_id][out_id])

    def _apply_route(self, chan_id, out_id):
        sink = self.sink_for(chan_id)
        output = self.outputs_by_id[out_id]
        enabled = self.config["routes"][chan_id][out_id]
        pairs = (
            (f"{sink}_out:output_FL", output["port_l"]),
            (f"{sink}_out:output_FR", output["port_r"]),
        )
        for source_port, dest_port in pairs:
            if enabled:
                self._backend.connect(source_port, dest_port)
            else:
                self._backend.disconnect(source_port, dest_port)

    # ------------------------------------------------------------------
    # Applying and verifying the whole graph

    def apply_all(self):
        """(Re)applies every piece of state - used at startup and to self-heal."""
        for chan in self.config["channels"]:
            chan_id = chan["id"]
            self._backend.set_sink_volume(chan["sink"], self.config["volume"][chan_id])
            self._apply_mute(chan_id)
            for out_id in self.outputs_by_id:
                self._apply_route(chan_id, out_id)

        for inp in self.config["inputs"]:
            input_id = inp["id"]
            self._backend.set_sink_volume(inp["target_sink"], self.config["volume"][input_id])
            self._apply_mute(input_id)
            # Start or stop this strip's effects chain before linking anything,
            # so the nodes the links point at already exist.
            if self._filters:
                self._filters.apply(input_id, inp["label"], inp.get("effects"))
            dest_l, dest_r = self.input_destination(inp)
            for source in self.input_sources(inp):
                capture_l, capture_r = self.capture_ports_for_source(source)
                self._backend.connect(capture_l, dest_l)
                self._backend.connect(capture_r, dest_r)
                self._backend.set_source_volume(source["name"], source.get("volume", 100))
            for chain_out, sink_in in self.effects_tail_links(inp):
                self._backend.connect(chain_out, sink_in)

        for out_id in self.outputs_by_id:
            self._backend.set_sink_volume(
                self.output_sink_for(out_id), self.config["output_volume"][out_id]
            )
            self._apply_output_mute(out_id)

    def expected_links(self):
        """Every (source_port, dest_port) the current routing implies."""
        links = set()
        for chan in self.config["channels"]:
            sink = chan["sink"]
            for out_id, output in self.outputs_by_id.items():
                if self.config["routes"][chan["id"]][out_id]:
                    links.add((f"{sink}_out:output_FL", output["port_l"]))
                    links.add((f"{sink}_out:output_FR", output["port_r"]))
        for inp in self.config["inputs"]:
            dest_l, dest_r = self.input_destination(inp)
            for capture_l, capture_r in self.capture_ports_for_input(inp):
                links.add((capture_l, dest_l))
                links.add((capture_r, dest_r))
            links.update(self.effects_tail_links(inp))
        return links

    def missing_links(self):
        """Expected links absent from the live graph.

        PipeWire restarts and device profile changes silently drop manual links,
        which otherwise means audio just stops until the routing is rebuilt by
        hand. The UI's watchdog uses this to notice and repair.
        """
        present = self._backend.present_links()
        if not present:
            return set()  # cannot tell right now; assume fine rather than thrash
        return {link for link in self.expected_links() if link not in present}
