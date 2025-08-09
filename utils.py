# utils.py
# This file contains utility functions for the RFID application.

def strength_to_percentage(strength_val: int) -> float:
    """
    Convert a raw signal strength value to a percentage (0-100).
    The TSL 1128 reader provides values from 0 to 1000.
    """
    return (strength_val / 1000) * 100
