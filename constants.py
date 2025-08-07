"""Shared constants for the RFID GUI."""

VERSION_LABELS = {
    "MF": "Manufacturer",
    "US": "Unit serial",
    "PV": "Protocol version",
    "UF": "Firmware version",
    "UB": "Bootloader version",
    "RS": "RFID serial",
    "RF": "RFID firmware",
    "RB": "RFID bootloader",
    "AS": "Assembly serial",
    "BA": "Bluetooth address",
    "BV": "Battery voltage",
}

BATTERY_LABELS = {
    "BP": "Charge level",
    "CH": "Charging state",
}

# Maximum number of signal strength samples to retain per tag
STRENGTH_HISTORY_LEN = 500
