"""Main window for the RFID GUI application."""

import sys
import re
import serial
import serial.tools.list_ports
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
from PyQt5.QtCore import QTimer
from typing import Optional

from serial_worker import SerialWorker
from parsers import ResponseParser, parse_payload
from constants import VERSION_LABELS, BATTERY_LABELS


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self):
        """Configure widgets and initialize member data."""
        super().__init__()
        self.setWindowTitle("TSL 1128 Interface")
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

        # Connect/Disconnect
        h0 = QHBoxLayout()
        for name, slot in [
            ("Connect", self.connect_serial),
            ("Disconnect", self.disconnect_serial),
        ]:
            b = QPushButton(name)
            b.clicked.connect(slot)
            h0.addWidget(b)
        self.poll_toggle = QPushButton("Polling On")
        self.poll_toggle.setCheckable(True)
        self.poll_toggle.setChecked(True)
        self.poll_toggle.clicked.connect(self.toggle_polling)
        h0.addWidget(self.poll_toggle)
        left_layout.addLayout(h0)

        # Shortcuts
        h2 = QHBoxLayout()
        for txt, cmd in [
            ("Version", ".vr"),
            ("Battery", ".bl"),
            ("Inventory", ".iv"),
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
        b_clear = QPushButton("Clear Console")
        b_clear.clicked.connect(self.clear_console)
        left_layout.addWidget(b_clear)

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
            """
            QProgressBar {border:1px solid #555;border-radius:2px;background:#eee;}
            QProgressBar::chunk {background-color:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #66f,stop:1 #9cf);}
            """
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
            """
            QProgressBar {border:1px solid #555;border-radius:2px;background:#eee;}
            QProgressBar::chunk {background-color:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #66f,stop:1 #9cf);}
            """
        )
        battery_container.addWidget(self.battery_bar)
        self.battery_display = QTextEdit(readOnly=True)
        battery_container.addWidget(self.battery_display)
        right_layout.addLayout(battery_container)

        # Auto‑poll
        self.poll_interval = 10  # seconds
        self.progress_range = 100
        self.progress = 0
        self.poll_enabled = True
        self.version_bar.setRange(0, self.progress_range)
        self.battery_bar.setRange(0, self.progress_range)
        self.version_bar.setValue(0)
        self.battery_bar.setValue(0)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)
        self.timer.start(100)

        self.worker = None
        self.refresh_ports()

        self.silent_queue: list[str] = []
        self.current_cmd: Optional[str] = None
        self.current_silent = False
        self.response_parser = ResponseParser()
        self.version_info: dict[str, str] = {}
        self.battery_info: dict[str, str] = {}

    @staticmethod
    def _port_available(dev: str) -> bool:
        """Return True if a port can be opened."""
        try:
            s = serial.Serial(dev)
            s.close()
            return True
        except (serial.SerialException, OSError):
            return False

    def refresh_ports(self):
        """Rescan available serial ports and categorize them."""
        ports = serial.tools.list_ports.comports()
        usb = []
        bt = []
        for p in ports:
            desc = (p.description or "").lower()
            if "bluetooth" in desc:
                bt.append(p)
            else:
                usb.append(p)

        self.combo.clear()

        def _add_group(label, plist):
            if not plist:
                return
            self.combo.addItem(label)
            self.combo.model().item(self.combo.count() - 1).setEnabled(False)
            for info in plist:
                status = (
                    "connected"
                    if self._port_available(info.device)
                    else "unavailable"
                )
                txt = f"{info.device} — {info.description} ({status})"
                self.combo.addItem(txt, info.device)

        _add_group("USB ports", usb)
        _add_group("Bluetooth ports", bt)

        if not ports:
            self.combo.addItem("<no ports>", "")

        if self.worker:
            self.worker.stop()
            self.worker = None

    def connect_serial(self):
        """Create and start the worker for the chosen port."""
        port = self.combo.currentData()
        if not port or self.worker:
            return
        self.worker = SerialWorker(port)
        self.worker.connected.connect(self.on_connected)
        self.worker.disconnected.connect(self.on_disconnected)
        self.worker.line_received.connect(self.process_line)
        self.worker.command_sent.connect(self.on_command_sent)
        self.worker.start()

    def disconnect_serial(self):
        """Stop the worker and reset the UI."""
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.progress = 0
        self.version_bar.setValue(0)
        self.battery_bar.setValue(0)

    def toggle_polling(self):
        """Turn automatic status polling on or off."""
        self.poll_enabled = self.poll_toggle.isChecked()
        self.poll_toggle.setText("Polling On" if self.poll_enabled else "Polling Off")
        if self.poll_enabled and self.worker:
            self.poll_status()

    def poll_status(self):
        """Issue queued commands for status updates."""
        for cmd in (".vr", ".bl"):
            self.send_command(cmd, silent=True)
        self.progress = 0

    def clear_console(self):
        """Clear the log output area."""
        self.log.clear()

    def send_command(self, cmd: str, silent: bool = False):
        """Send a command string to the reader."""
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

        self.worker.write(cmd, not silent)
        self.input.clear()

    def on_connected(self, port: str):
        """Handle reader connection."""
        self.log.append(f"✅ Connected to {port}")
        if self.poll_enabled:
            self.poll_status()

    def on_disconnected(self):
        """Handle reader disconnection."""
        self.log.append("🔌 Disconnected")
        self.progress = 0
        self.version_bar.setValue(0)
        self.battery_bar.setValue(0)

    def on_command_sent(self, cmd: str):
        """Log sent commands that aren't silent."""
        if self.silent_queue and self.silent_queue[0] == cmd:
            return
        self.log.append(f">> {cmd}")

    def process_line(self, line: str):
        """Process a single line of reader output."""
        resp = self.response_parser.feed(line)

        if self.response_parser.command and self.current_cmd != self.response_parser.command:
            self.current_cmd = self.response_parser.command
            self.current_silent = bool(self.silent_queue and self.silent_queue[0] == self.current_cmd)

        if resp is None:
            if line.startswith("CS:"):
                return
            if not self.current_silent:
                if ":" not in line and re.fullmatch(r"[0-9A-Fa-f]+", line.strip()):
                    tag = line.strip()
                    self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
                    self.update_table()
                self.log.append(f"<< {line}")
            return

        parse_payload(
            resp.command,
            resp.payload,
            {
                "version_info": self.version_info,
                "battery_info": self.battery_info,
            },
        )
        self.update_version_display()
        self.update_battery_display()

        # Payload lines were already logged as they arrived while collecting the
        # response, so avoid logging them again here. Tag counts have also been
        # updated at that time.

        if not self.current_silent:
            if resp.ok:
                self.log.append("<< OK:")
            else:
                self.log.append(f"<< ER: {resp.error}")

        if self.current_silent and self.silent_queue:
            self.silent_queue.pop(0)
        self.current_silent = False
        self.current_cmd = None
        self.update_table()

    def update_table(self):
        """Update the table with tag counts."""
        self.table.setRowCount(len(self.tag_counts))
        for r, (tag, count) in enumerate(self.tag_counts.items()):
            self.table.setItem(r, 0, QTableWidgetItem(tag))
            self.table.setItem(r, 1, QTableWidgetItem(str(count)))

    def update_version_display(self):
        """Display collected version information."""
        txt = "\n".join(f"{k}: {v}" for k, v in self.version_info.items())
        self.version_display.setPlainText(txt)

    def update_battery_display(self):
        """Display collected battery information."""
        txt = "\n".join(f"{k}: {v}" for k, v in self.battery_info.items())
        self.battery_display.setPlainText(txt)

    def update_progress(self):
        """Advance progress bars and poll when complete."""
        if not self.poll_enabled or not self.worker:
            self.progress = 0
            self.version_bar.setValue(0)
            self.battery_bar.setValue(0)
            return

        self.progress += 1
        if self.progress > self.progress_range:
            self.poll_status()
            self.progress = 0

        self.version_bar.setValue(self.progress)
        self.battery_bar.setValue(self.progress)

    def closeEvent(self, e):
        """Cleanly stop the worker before closing."""
        if self.worker:
            self.worker.stop()
        e.accept()


def main() -> None:
    """Launch the GUI application."""
    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
