#!/usr/bin/env python3
"""Toggle DTR/RTS on a USB serial adapter to wake the TSL 1128.

This utility finds a likely serial port and briefly drops the control lines
so the reader starts responding without needing to unplug it.
"""

import argparse
import glob
import time

import serial


def find_port() -> str | None:
    """Return the first matching USB serial port or ``None``."""
    ports = glob.glob("/dev/tty.usbserial*") + glob.glob("/dev/tty.usbmodem*")
    return ports[0] if ports else None


def kick(port: str | None) -> None:
    port = port or find_port()
    if not port:
        print("No USB serial port found")
        return
    with serial.Serial(port, 115200, timeout=1) as ser:
        ser.dtr = False
        ser.rts = False
        time.sleep(0.05)
        ser.dtr = True
        ser.rts = True
    print(f"Kicked {port}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", help="Serial port (auto-detect if omitted)")
    args = parser.parse_args()
    kick(args.port)


if __name__ == "__main__":
    main()
