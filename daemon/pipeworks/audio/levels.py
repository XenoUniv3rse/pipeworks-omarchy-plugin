"""Conversion between raw sample peaks and meter positions."""
import math

from .. import settings


def peak_to_level(peak):
    """Maps a linear 0.0-1.0 sample peak to a 0.0-1.0 position on a dB scale.

    A linear scale is useless for metering: everyday audio rarely approaches
    full scale, so normal-volume content would barely lift the bar off the
    floor.
    """
    if peak <= 0:
        return 0.0
    decibels = 20 * math.log10(peak)
    floor = settings.METER_FLOOR_DB
    return max(0.0, min(1.0, (decibels - floor) / -floor))
