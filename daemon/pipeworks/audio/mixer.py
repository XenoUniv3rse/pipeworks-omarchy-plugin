"""Mixing domain logic.

Holds the rules - what mute means when something else is soloed, which links a
routing table implies, what happens when a strip is added - and delegates every
side effect: audio operations to an AudioBackend, persistence to a
ConfigRepository, deferred work to an injected scheduler. That keeps this module
free of PipeWire, subprocess and GTK, and makes the rules testable with fakes.
"""
import time

from .. import settings

CHANNEL = "channel"
INPUT = "input"
OUTPUT = "output"


class Mixer:
    def __init__(self, config, repository, backend, scheduler):
        self.config = config
        self._repository = repository
        self._backend = backend
        self._schedule = scheduler

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

    def capture_ports_for_input(self, inp):
        """Where an input's audio comes from.

        Tolerates configs written before these were recorded - the original
        hardcoded mic predates them - by resolving from the device instead.
        """
        if inp.get("capture_l") and inp.get("capture_r"):
            return inp["capture_l"], inp["capture_r"]
        return self._backend.capture_ports(inp["source"])

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
                "source": source_name,
                "target_sink": f"virtual_{slug}",
                "capture_l": capture_l,
                "capture_r": capture_r,
            }
        )
        self.inputs_by_id[slug] = self.config["inputs"][-1]
        self.config["volume"][slug] = 70
        self.config["muted"][slug] = False
        self._reprovision()
        return slug

    def remove_input(self, input_id):
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
        """Points an existing input strip at a different capture device."""
        inp = self.inputs_by_id[input_id]
        old_l, old_r = self.capture_ports_for_input(inp)
        self._backend.disconnect(old_l, f"{inp['target_sink']}:playback_FL")
        self._backend.disconnect(old_r, f"{inp['target_sink']}:playback_FR")

        inp["source"] = source_name
        inp["capture_l"], inp["capture_r"] = self._backend.capture_ports(source_name)
        self._repository.save(self.config)
        self.apply_all()

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

    def set_volume(self, strip_id, percent):
        percent = max(0, min(100, percent))
        self.config["volume"][strip_id] = percent
        self.on_state_changed()
        self._throttled(f"strip:{strip_id}", lambda: self._apply_volume(strip_id))

    def set_output_volume(self, out_id, percent):
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
            capture_l, capture_r = self.capture_ports_for_input(inp)
            self._backend.connect(capture_l, f"{inp['target_sink']}:playback_FL")
            self._backend.connect(capture_r, f"{inp['target_sink']}:playback_FR")

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
            capture_l, capture_r = self.capture_ports_for_input(inp)
            links.add((capture_l, f"{inp['target_sink']}:playback_FL"))
            links.add((capture_r, f"{inp['target_sink']}:playback_FR"))
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
