#!/usr/bin/env python3
"""
Robust PyQt5 TSL 1128 GUI with clean Connect/Disconnect
"""
import sys
import serial
import serial.tools.list_ports
import re
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QComboBox,
    QLineEdit,
    QTextEdit,
    QHBoxLayout,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
)
from PyQt5.QtCore import QThread
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import QTimer

# Friendly labels for version and battery fields
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
    # older field names for compatibility
    "VR": "Firmware version",
    "AP": "Model",
    "SN": "Serial number",
}

BATTERY_LABELS = {
    "BV": "Battery voltage",
    "PC": "Charge level",
    "BP": "Charge level",
    "CH": "Charging state",
}


class SerialWorker(QThread):
    data_received = pyqtSignal(str)

    def __init__(s, port, baud=115200):
        super().__init__()
        s.port = port
        s.baud = baud
        s._running = True
        s.ser = None

    def run(s):
        try:
            s.ser = serial.Serial(s.port, s.baud, timeout=1)
            s.data_received.emit(f"✅ Connected to {s.port}")
            buf = ""
            while s._running:
                try:
                    n = s.ser.in_waiting or 1
                    raw = s.ser.read(n).decode(errors="ignore")
                except (serial.SerialException, OSError):
                    break
                if raw:
                    buf += raw
                    parts = buf.split("\r\n")
                    buf = parts.pop()
                    for line in parts:
                        if line.strip():
                            s.data_received.emit(f"<< {line}")
        finally:
            if s.ser and s.ser.is_open:
                s.ser.close()
                s.data_received.emit("🔌 Disconnected")

    def write(s, cmd: str, echo=True):
        if not (s.ser and s.ser.is_open):
            return
        for p in cmd.split(";"):
            s.ser.write((p + "\r\n").encode())
            if echo:
                s.data_received.emit(f">> {p}")

    def stop(s):
        s._running = False  # signal thread to exit; actual close in run()
        s.wait()            # block until the thread has fully shut down


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TSL 1128 Interface")
        self.resize(800, 600)

        w = QWidget()
        self.setCentralWidget(w)
        root = QHBoxLayout(w)
        left_layout = QVBoxLayout()
        root.addLayout(left_layout, 1)
        right_layout = QVBoxLayout()
        root.addLayout(right_layout)
        # Port selector + Refresh
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Port:"))
        self.combo = QComboBox()
        h1.addWidget(self.combo)
        b_refresh = QPushButton("🔄 Refresh")
        b_refresh.clicked.connect(self.refresh_ports)
        h1.addWidget(b_refresh)
        left_layout.addLayout(h1)
        # Connect/Disconnect/Poll
        h0 = QHBoxLayout()
        for name, slot in [
            ("Connect", self.connect_serial),
            ("Disconnect", self.disconnect_serial),
            ("Poll Status", self.poll_status),
        ]:
            b = QPushButton(name)
            b.clicked.connect(slot)
            h0.addWidget(b)
        left_layout.addLayout(h0)
        # Shortcuts
        h2 = QHBoxLayout()
        for txt, cmd in [
            ("Version", ".vr"),
            ("Battery", ".bl"),
            ("Inventory", ".ec on;.iv;.ec off"),
        ]:
            btn = QPushButton(txt)
            btn.clicked.connect(lambda _, c=cmd: self.send_command(c))
            h2.addWidget(btn)
        left_layout.addLayout(h2)
        # Manual
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("Command:"))
        self.input = QLineEdit()
        h3.addWidget(self.input)
        b_send = QPushButton("Send")
        b_send.clicked.connect(lambda: self.send_command(self.input.text()))
        h3.addWidget(b_send)
        left_layout.addLayout(h3)
        # Log + Table
        self.log = QTextEdit(readOnly=True)
        left_layout.addWidget(self.log)

        self.tag_counts = {}
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Tag", "Count"])
        left_layout.addWidget(self.table)
        # Right side info containers
        right_layout.addWidget(QLabel("Version"))
        version_container = QVBoxLayout()
        self.version_bar = QProgressBar()
        self.version_bar.setTextVisible(False)
        self.version_bar.setFixedHeight(4)
        self.version_bar.setStyleSheet(
            "QProgressBar::chunk { background-color: blue; }"
        )
        version_container.addWidget(self.version_bar)
        self.version_display = QTextEdit(readOnly=True)
        version_container.addWidget(self.version_display)
        right_layout.addLayout(version_container)

        right_layout.addWidget(QLabel("Battery"))
        battery_container = QVBoxLayout()
        self.battery_bar = QProgressBar()
        self.battery_bar.setTextVisible(False)
        self.battery_bar.setFixedHeight(4)
        self.battery_bar.setStyleSheet(
            "QProgressBar::chunk { background-color: blue; }"
        )
        battery_container.addWidget(self.battery_bar)
        self.battery_display = QTextEdit(readOnly=True)
        battery_container.addWidget(self.battery_display)
        right_layout.addLayout(battery_container)
        # Auto‑poll
        self.poll_interval = 10
        self.countdown = self.poll_interval
        self.version_bar.setRange(0, self.poll_interval)
        self.battery_bar.setRange(0, self.poll_interval)
        self.version_bar.setValue(0)
        self.battery_bar.setValue(0)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)

        self.worker = None
        self.refresh_ports()

        self.silent_queue = []
        self.current_cmd = None
        self.current_silent = False
        self.version_info = {}
        self.battery_info = {}

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        self.combo.clear()
        for p in ports:
            self.combo.addItem(f"{p.device} — {p.description}", p.device)
        if not ports:
            self.combo.addItem("<no ports>", "")

        items = [self.combo.itemText(i) for i in range(self.combo.count())]
        self.log.append(f"🔄 Ports: {items}")

        if self.worker:
            self.worker.stop()
            self.worker = None

    def connect_serial(self):
        port = self.combo.currentData()
        if not port or self.worker:
            return
        self.worker = SerialWorker(port)
        self.worker.data_received.connect(self.process_data)
        self.worker.start()

    def disconnect_serial(self):
        if self.worker:
            self.worker.stop()
            self.worker = None

    def poll_status(self):
        for cmd in (".vr", ".bl"):
            self.send_command(cmd, silent=True)
        self.countdown = self.poll_interval

    def send_command(self, cmd: str, silent=False):
        cmd = cmd.strip()
        if not cmd:
            return

        if not self.worker:
            if not silent:
                self.log.append("⚠️ Not connected")
            return

        if silent:
            for part in cmd.split(";"):
                self.silent_queue.append(part.strip())
        else:
            self.log.append(f">> {cmd}")

        self.worker.write(cmd, echo=not silent)
        self.input.clear()

    def process_data(self, text):
        if text.startswith("<< "):
            line = text[3:]
            self.parse_line(line)
            if (
                not self.current_silent
                and ":" not in line
                and re.fullmatch(r"[0-9A-Fa-f]+", line.strip())
            ):
                tag = line.strip()
                self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
                self.update_table()
            if not self.current_silent:
                self.log.append(text)
            if line == "OK:" or line.startswith("ER:"):
                if self.current_silent and self.silent_queue:
                    self.silent_queue.pop(0)
                self.current_silent = False
                self.current_cmd = None
        else:
            if not self.current_silent:
                self.log.append(text)

    def update_table(self):
        self.table.setRowCount(len(self.tag_counts))
        for r, (tag, count) in enumerate(self.tag_counts.items()):
            self.table.setItem(r, 0, QTableWidgetItem(tag))
            self.table.setItem(r, 1, QTableWidgetItem(str(count)))

    def parse_line(self, line: str):
        if line.startswith("CS:"):
            self.current_cmd = line[4:].strip()
            self.current_silent = bool(
                self.silent_queue and self.silent_queue[0] == self.current_cmd
            )
        elif line == "OK:" or line.startswith("ER:"):
            pass
        elif self.current_cmd == ".vr":
            if ':' in line:
                k, v = line.split(':', 1)
                label = VERSION_LABELS.get(k.strip(), k.strip())
                self.version_info[label] = v.strip()
                self.update_version_display()
        elif self.current_cmd == ".bl":
            if ':' in line:
                k, v = line.split(':', 1)
                field = k.strip()
                label = BATTERY_LABELS.get(field, field)
                val = v.strip()
                if field == "BV":
                    self.battery_info[label] = f"{val}mV"
                elif field in ("PC", "BP"):
                    self.battery_info[label] = f"{val}%"
                else:
                    self.battery_info[label] = val
                self.update_battery_display()

    def update_version_display(self):
        txt = "\n".join(f"{k}: {v}" for k, v in self.version_info.items())
        self.version_display.setPlainText(txt)

    def update_battery_display(self):
        txt = "\n".join(f"{k}: {v}" for k, v in self.battery_info.items())
        self.battery_display.setPlainText(txt)

    def update_countdown(self):
        progress = self.poll_interval - self.countdown
        self.version_bar.setValue(progress)
        self.battery_bar.setValue(progress)
        self.countdown -= 1
        if self.countdown < 0:
            self.poll_status()
            self.countdown = self.poll_interval

    def closeEvent(self, e):
        if self.worker:
            self.worker.stop()
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())
