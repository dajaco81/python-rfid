# serial_worker.py
# This file contains the SerialWorker class for handling communication on a separate thread.

import serial
import threading
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class SerialWorker(QObject):
    """
    A worker thread to handle serial port communication without blocking the GUI.
    """
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    line_received = pyqtSignal(str)
    command_sent = pyqtSignal(str)

    def __init__(self, port):
        super().__init__()
        self._port = port
        self._serial_thread = None
        self._stop_event = threading.Event()
        self._serial_connection = None
        self._write_lock = threading.Lock()
        
    def start(self):
        """Start the serial communication thread."""
        self._stop_event.clear()
        self._serial_thread = threading.Thread(target=self._run)
        self._serial_thread.daemon = True
        self._serial_thread.start()

    def stop(self):
        """Request the serial communication thread to stop."""
        self._stop_event.set()
        if self._serial_connection and self._serial_connection.is_open:
            self._serial_connection.close()

    def _run(self):
        """The main loop for the serial thread."""
        try:
            self._serial_connection = serial.Serial(
                self._port,
                baudrate=115200,
                timeout=0.1,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                rtscts=True
            )
            self.connected.emit(self._port)
            while not self._stop_event.is_set():
                if self._serial_connection.in_waiting:
                    line = self._serial_connection.readline().decode('ascii').strip()
                    if line:
                        self.line_received.emit(line)
        except serial.SerialException as e:
            print(f"Serial port error: {e}")
        finally:
            self.disconnected.emit()

    def write(self, data, log=True):
        """Write data to the serial port."""
        if not self._serial_connection or not self._serial_connection.is_open:
            return
        
        with self._write_lock:
            data_to_write = data.encode('ascii') + b'\r\n'
            self._serial_connection.write(data_to_write)
        if log:
            self.command_sent.emit(data)
