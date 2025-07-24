"""Threaded serial communication helper."""

import serial
from PyQt5.QtCore import QThread, pyqtSignal


class SerialWorker(QThread):
    """Read and write serial data in a background thread."""

    data_received = pyqtSignal(str)

    def __init__(self, port: str, baud: int = 115200):
        """Initialize the worker thread."""
        super().__init__()
        self.port = port
        self.baud = baud
        self._running = True
        self.ser = None

    def run(self):
        """Read lines from the serial port and emit them."""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
            self.data_received.emit(f"✅ Connected to {self.port}")
            buf = ""
            while self._running:
                try:
                    n = self.ser.in_waiting or 1
                    raw = self.ser.read(n).decode(errors="ignore")
                except (serial.SerialException, OSError):
                    break
                if raw:
                    buf += raw
                    parts = buf.split("\r\n")
                    buf = parts.pop()
                    for line in parts:
                        if line.strip():
                            self.data_received.emit(f"<< {line}")
        finally:
            if self.ser and self.ser.is_open:
                self.ser.close()
                self.data_received.emit("🔌 Disconnected")

    def write(self, cmd: str, echo: bool = True):
        """Write a command to the device."""
        if not (self.ser and self.ser.is_open):
            return
        for part in cmd.split(";"):
            self.ser.write((part + "\r\n").encode())
            if echo:
                self.data_received.emit(f">> {part}")

    def stop(self):
        """Request the thread stop and wait for completion."""
        self._running = False
        self.wait()
