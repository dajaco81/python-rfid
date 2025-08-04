"""Utility functions for signal strength conversion."""


def strength_to_percentage(strength: float) -> int:
    """Convert RSSI strength in dBm to a percentage.

    Strength values at or below -90 map to 0 and values at or above -25 map to
    100. Values between are scaled linearly.
    """
    if strength <= -90:
        return 0
    if strength >= -25:
        return 100
    # Linear interpolation over the range [-90, -25]
    return int(round((strength + 90) * 100 / 65))

