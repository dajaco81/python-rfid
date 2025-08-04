"""Main window for the RFID GUI application."""

import sys
import re
import serial # type: ignore
import serial.tools.list_ports # type: ignore
from PyQt5.QtWidgets import ( # type: ignore
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
from PyQt5.QtCore import QTimer # type: ignore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas # type: ignore
from matplotlib.figure import Figure # type: ignore
from typing import Optional

from serial_worker import SerialWorker
from parsers import ResponseParser, parse_payload
from utils import strength_to_percentage
from constants import STRENGTH_HISTORY_LEN


class MplCanvas(FigureCanvas):
    """Simple matplotlib canvas for live plots."""

    def __init__(self) -> None:
        fig = Figure(figsize=(5, 3))
        super().__init__(fig)
        self.axes = fig.add_subplot(111)


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
        self.session_toggle = QPushButton("Quiet Tags")
        self.session_toggle.setCheckable(True)
        self.session_toggle.setChecked(False)
        self.session_toggle.toggled.connect(self.toggle_session)
        h0.addWidget(self.session_toggle)
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

        b_clear_table = QPushButton("Clear Tags")
        b_clear_table.clicked.connect(self.clear_table)
        left_layout.addWidget(b_clear_table)

        self.tag_counts = {}
        self.tag_strengths: dict[str, list[float]] = {}
        self.tag_min_strengths: dict[str, float] = {}
        self.tag_max_strengths: dict[str, float] = {}
        # Maximum number of signal strength samples to retain per tag
        self.strength_history_len = STRENGTH_HISTORY_LEN
        self.pending_tag: Optional[str] = None
        self.selected_tag: Optional[str] = None
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tag", "Count", "Min Strength", "Max Strength"])
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        left_layout.addWidget(self.table)
        h_filter = QHBoxLayout()
        b_filter = QPushButton("Filter Tag")
        b_filter.clicked.connect(self.filter_selected_tag)
        h_filter.addWidget(b_filter)
        b_clear_filter = QPushButton("Clear Filter")
        b_clear_filter.clicked.connect(self.clear_tag_filter)
        h_filter.addWidget(b_clear_filter)
        left_layout.addLayout(h_filter)

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

        right_layout.addWidget(QLabel("Signal Strength"))
        self.strength_canvas = MplCanvas()
        right_layout.addWidget(self.strength_canvas)

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
        self.scanning = False
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
            if "usbserial" in p.device:
                usb.append(p)
            else:
                bt.append(p)

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
                txt = f"{info.device} ({status})"
                self.combo.addItem(txt, info.device)

        _add_group("USB ports", usb)
        _add_group("Bluetooth ports", bt)

        if not ports:
            self.combo.addItem("<no ports>", "")

        # Don't keep a previously selected index that might now refer to a
        # disabled header. Select the first real port or nothing.
        self.combo.setCurrentIndex(-1)
        for i in range(self.combo.count()):
            if self.combo.itemData(i):
                self.combo.setCurrentIndex(i)
                break

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
        self.scanning = False
        self.pending_tag = None

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

    def clear_table(self) -> None:
        """Remove all tags from the table and reset history."""
        self.tag_counts.clear()
        self.tag_strengths.clear()
        self.tag_min_strengths.clear()
        self.tag_max_strengths.clear()
        self.update_table()
        self.update_strength_plot()

    def filter_selected_tag(self) -> None:
        """Apply a tag ID filter using the currently selected tag."""
        if not self.worker:
            self.log.append("⚠️ Not connected")
            return
        if not self.selected_tag:
            self.log.append("⚠️ No tag selected")
            return
        tag = self.selected_tag
        length = len(tag) * 4
        cmd = f".iv -s 0 -a 0 -b epc -o 29 -l {length} -m {tag}"
        self.send_command(cmd)

    def clear_tag_filter(self) -> None:
        """Clear any active tag ID filter."""
        if not self.worker:
            self.log.append("⚠️ Not connected")
            return
        self.send_command(".iv -s 0 -r")

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

    def send_inventory_setup(self) -> None:
        """Configure inventory command based on session toggle."""
        session = "s0" if self.session_toggle.isChecked() else "s1"
        setup_cmd = f".iv -r on -e off -c off -dt off -ix off -qa dyn -qs {session} -tf on -o 29 -al off -n"
        self.send_command(setup_cmd, silent=True)

    def toggle_session(self, checked: bool) -> None:
        """Switch between quiet and zero-persistence modes."""
        self.session_toggle.setText("Zero Persistence" if checked else "Quiet Tags")
        if self.worker:
            self.send_inventory_setup()

    def on_connected(self, port: str):
        """Handle reader connection."""
        self.log.append(f"✅ Connected to {port}")
        self.tag_counts.clear()
        self.tag_strengths.clear()
        self.update_table()
        self.update_strength_plot()
        self.send_inventory_setup()
        self.scanning = True
        if self.poll_enabled:
            self.poll_status()

    def on_disconnected(self):
        """Handle reader disconnection."""
        self.log.append("🔌 Disconnected")
        self.progress = 0
        self.version_bar.setValue(0)
        self.battery_bar.setValue(0)
        self.scanning = False
        self.pending_tag = None

    def on_command_sent(self, cmd: str):
        """Log sent commands that aren't silent."""
        if self.silent_queue and self.silent_queue[0] == cmd:
            return
        self.log.append(f">> {cmd}")

    def process_line(self, line: str):
        """Process a single line of reader output."""
        if line.startswith("EP:") or line.startswith("RI:"):
            self.handle_inventory_line(line)
            return

        resp = self.response_parser.feed(line)

        if self.response_parser.command and self.current_cmd != self.response_parser.command:
            self.current_cmd = self.response_parser.command
            self.current_silent = bool(self.silent_queue and self.silent_queue[0] == self.current_cmd)

        if resp is None:
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
                "tag_counts": self.tag_counts,
                "tag_strengths": self.tag_strengths,
                "tag_min_strengths": self.tag_min_strengths,
                "tag_max_strengths": self.tag_max_strengths,
            },
        )
        self.update_version_display()
        self.update_battery_display()

        # Payload lines were already logged as they arrived while collecting the
        # response, so avoid logging them again here. Tag counts are updated by
        # the inventory decoder when the response completes.

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
        """Update the table with tag counts and min/max strength."""
        self.table.setRowCount(len(self.tag_counts))
        for r, (tag, count) in enumerate(self.tag_counts.items()):
            self.table.setItem(r, 0, QTableWidgetItem(tag))
            self.table.setItem(r, 1, QTableWidgetItem(str(count)))
            min_val = self.tag_min_strengths.get(tag)
            max_val = self.tag_max_strengths.get(tag)
            min_txt = f"{min_val}%" if isinstance(min_val, (int, float)) else ""
            max_txt = f"{max_val}%" if isinstance(max_val, (int, float)) else ""
            self.table.setItem(r, 2, QTableWidgetItem(min_txt))
            self.table.setItem(r, 3, QTableWidgetItem(max_txt))

    def update_version_display(self):
        """Display collected version information."""
        txt = "\n".join(f"{k}: {v}" for k, v in self.version_info.items())
        self.version_display.setPlainText(txt)

    def update_battery_display(self):
        """Display collected battery information."""
        txt = "\n".join(f"{k}: {v}" for k, v in self.battery_info.items())
        self.battery_display.setPlainText(txt)

    def on_table_selection_changed(self) -> None:
        """Update selected tag for strength plotting."""
        items = self.table.selectedItems()
        if not items:
            self.selected_tag = None
            self.strength_canvas.axes.cla()
            self.strength_canvas.draw()
            return
        row = self.table.currentRow()
        tag_item = self.table.item(row, 0)
        if tag_item:
            self.selected_tag = tag_item.text()
            self.update_strength_plot()

    def update_strength_plot(self) -> None:
        """Draw signal strength history for the selected tag."""
        if not self.selected_tag:
            return
        data = [v for v in self.tag_strengths.get(self.selected_tag, []) if v is not None]
        ax = self.strength_canvas.axes
        ax.cla()
        if data:
            ax.plot(range(len(data)), data, marker="o")
            ax.set_ylim(0, 100)
        ax.set_xlabel("Read")
        ax.set_ylabel("Signal strength (%)")
        self.strength_canvas.draw()

    def handle_inventory_line(self, line: str) -> None:
        """Process inventory EP/RI lines."""
        if line.startswith("EP:"):
            tag = line[3:].strip()
            if not tag:
                return
            self.pending_tag = tag
            self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
            hist = self.tag_strengths.setdefault(tag, [])
            hist.append(None)
            if len(hist) > self.strength_history_len:
                hist.pop(0)
            self.update_table()
            if self.selected_tag == tag:
                self.update_strength_plot()
        elif line.startswith("RI:"):
            val_str = line[3:].strip()
            try:
                strength = int(val_str)
            except ValueError:
                try:
                    strength = float(val_str)
                except ValueError:
                    strength = None
            if strength is not None:
                strength = strength_to_percentage(strength)
            if self.pending_tag:
                hist = self.tag_strengths.setdefault(self.pending_tag, [])
                if hist:
                    if hist[-1] is None:
                        hist[-1] = strength
                    else:
                        hist.append(strength)
                        if len(hist) > self.strength_history_len:
                            hist.pop(0)
                if strength is not None:
                    cur_min = self.tag_min_strengths.get(self.pending_tag)
                    if cur_min is None or strength < cur_min:
                        self.tag_min_strengths[self.pending_tag] = strength
                    cur_max = self.tag_max_strengths.get(self.pending_tag)
                    if cur_max is None or strength > cur_max:
                        self.tag_max_strengths[self.pending_tag] = strength
                if self.selected_tag == self.pending_tag:
                    self.update_strength_plot()
            self.update_table()
            self.pending_tag = None

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
