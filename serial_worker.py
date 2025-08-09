"""Threaded serial communication helper."""

import serial
import time
from PyQt5.QtCore import QThread, pyqtSignal

try:  # termios is unavailable on Windows
    import termios
    TermiosError = termios.error
except Exception:  # pragma: no cover - only executed on non-POSIX systems
    TermiosError = OSError


class SerialWorker(QThread):
    """Read and write serial data in a background thread."""

    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    line_received = pyqtSignal(str)
    command_sent = pyqtSignal(str)

    def __init__(self, port: str, baud: int = 115200):
        """Initialize the worker thread."""
        super().__init__()
        self.port = port
        self.baud = baud
        self._running = True
        self.ser = None

    def run(self):
        """Maintain a serial session, auto-reconnecting on failure."""
        buf = ""
        while self._running:
            try:
                self.ser = serial.Serial(
                    self.port,
                    self.baud,
                    timeout=1,
                    dsrdtr=True,
                    rtscts=True,
                    exclusive=False,
                )
                # Drop then raise control lines so the reader sees a fresh transition
                try:
                    self.ser.dtr = False
                    self.ser.rts = False
                    time.sleep(0.05)
                    self.ser.dtr = True
                    self.ser.rts = True
                except (serial.SerialException, OSError, TermiosError):
                    pass
                self.connected.emit(self.port)
                buf = ""
                while self._running:
                    try:
                        n = self.ser.in_waiting or 1
                        raw = self.ser.read(n).decode(errors="ignore")
                    except (serial.SerialException, OSError, TermiosError):
                        break
                    if raw:
                        buf = self._emit_lines(buf, raw)
            except (serial.SerialException, OSError, TermiosError):
                # Opening the port failed or the connection dropped
                pass
            finally:
                if self.ser and self.ser.is_open:
                    try:
                        self.ser.flush()
                    except (serial.SerialException, OSError, TermiosError):
                        # Device may already be gone
                        pass
                    # Drop lines so the reader knows we're disconnecting
                    try:
                        self.ser.dtr = False
                        self.ser.rts = False
                    except (serial.SerialException, OSError, TermiosError):
                        pass
                    try:
                        self.ser.close()
                    except (serial.SerialException, OSError, TermiosError):
                        pass
                self.ser = None
                self.disconnected.emit()
            if self._running:
                time.sleep(1)

    def _emit_lines(self, buf: str, raw: str) -> str:
        """Emit complete lines from serial data and return remaining buffer.

        Parameters
        ----------
        buf : str
            Remainder of the previous read containing a partial line.
        raw : str
            Newly read characters from the serial port.

        Returns
        -------
        str
            The trailing incomplete line to carry over to the next read.
        """
        buf += raw
        parts = buf.split("\r\n")
        buf = parts.pop()
        for line in parts:
            line = line.strip()
            if line:
                self.line_received.emit(line)
        return buf

    def write(self, cmd: str, echo: bool = True):
        """Write a command to the device."""
        if not (self.ser and self.ser.is_open):
            return
        for part in cmd.split(";"):
            try:
                self.ser.write((part + "\r\n").encode())
            except (serial.SerialException, OSError, TermiosError):
                break
            if echo:
                self.command_sent.emit(part)

    def stop(self):
        """Request the thread stop and wait for completion."""
        self._running = False
        self.wait()
