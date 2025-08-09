"""Main window for the RFID GUI application."""

# region imports

import sys
import re
import threading
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (
    QApplication, QMainWindow,
    QWidget, QLabel,
    QLayout, QPushButton,
    QComboBox, QLineEdit,
    QTextEdit, QFrame,
    QHBoxLayout, QVBoxLayout,
    QTableWidget, QTableWidgetItem,
    QProgressBar, QSizePolicy,
    QHeaderView, 
)
from PyQt5.QtCore import QTimer, QEvent, QObject
from PyQt5.QtGui import QColor

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from typing import Optional

from serial_worker import SerialWorker
from parsers import ResponseParser, parse_payload
from utils import strength_to_percentage
from constants import STRENGTH_HISTORY_LEN

# endregion

class c:
    red       = "#ffb3b3"
    green     = "#b3ffcc"
    blue      = "#b3d9ff"
    yellow    = "#fff5b3"
    orange    = "#ffd9b3"
    purple    = "#e0b3ff"
    pink      = "#ffccf2"
    cyan      = "#b3ffff"
    mint      = "#ccffe6"
    lavender  = "#e6e6fa"
    peach     = "#ffe5b4"
    gray      = "#e6e6e6"
    white     = "#ffffff"
    black     = "#000000"

    primary   = "#F2F2F2"
    secondary = "#DCE4F2"
    tertiary  = "#D8DCF2"
    highlight = "#A6A6A6"
    alert     = "#595959"

class MplCanvas(FigureCanvas):
    """Simple matplotlib canvas for live plots."""

    def __init__(self) -> None:
        fig = Figure(figsize=(5, 3))
        super().__init__(fig)
        self.axes = fig.add_subplot(111)

class LayoutFrameMixer:
    """Adding framing to layouts."""

    DEFAULT_SPACING = 4

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Always wrap the layout in a frame so spacing behaves consistently
        self._frame: QFrame = QFrame()
        self._frame.setLayout(self)
        self._style_base = "border-radius: 6px;"
        self._frame.setStyleSheet(f"QFrame {{{self._style_base}}}")

    def setColor(self, color):
        if color is None:
            self._frame.setStyleSheet(f"QFrame {{{self._style_base}}}")
            return
        self._frame.setStyleSheet(
            f"QFrame {{{self._style_base} background-color: {color};}}"
        )

    def noMargins(self):
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(self.DEFAULT_SPACING)
        self._frame.setContentsMargins(0, 0, 0, 0)

    def defaultMargins(self):
        self.setContentsMargins(-1, -1, -1, -1)
        self.setSpacing(self.DEFAULT_SPACING)
        self._frame.setContentsMargins(-1, -1, -1, -1)

    def attachTo(self, parent_layout: QLayout, *args) -> None:
        """Attach to parent layout using the frame wrapper."""
        parent_layout.addWidget(self._frame, *args)

class DHBoxLayout(LayoutFrameMixer, QHBoxLayout):
    """QHBoxLayout with optional debug border."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class DVBoxLayout(LayoutFrameMixer, QVBoxLayout):
    """QVBoxLayout with optional debug border."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class MainWindow(QMainWindow):
    """Primary application window."""
    def __init__(self):
        """Configure widgets and initialize member data."""
        super().__init__()
        self.setWindowTitle("TSL 1128 Interface")
        self.resize(1200, 800)

        root = DHBoxLayout()
        root.setColor(c.primary)
        self.setCentralWidget(root._frame)
        root.setSpacing(LayoutFrameMixer.DEFAULT_SPACING)

        left_container = DVBoxLayout()
        left_container.setColor(None)
        left_container.noMargins()
        self.generate_port_layout().attachTo(left_container)
        self.generate_connection_layout().attachTo(left_container)
        self.generate_shortcuts_layout().attachTo(left_container)
        self.generate_command_layout().attachTo(left_container)
        self.generate_log_layout().attachTo(left_container)
        self.generate_table_layout().attachTo(left_container)
        self.generate_tag_search_layout().attachTo(left_container)
        left_container.attachTo(root, 2)

        right_container = DVBoxLayout()
        right_container.setColor(None)
        right_container.noMargins()
        self.generate_version_layout().attachTo(right_container)
        self.generate_battery_layout().attachTo(right_container)
        self.generate_plot_layout().attachTo(right_container)
        right_container.attachTo(root, 1)

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
        self.auto_reconnect = False
        self.reconnecting = False
        self.scanning = False
        self.refresh_ports()

        self.silent_queue: list[str] = []
        self.current_cmd: Optional[str] = None
        self.current_silent = False
        self.response_parser = ResponseParser()
        self.version_info: dict[str, str] = {}
        self.battery_info: dict[str, str] = {}
        self.simulator = None
        self.pending_port: Optional[str] = None
        self.awaiting_vr = False
        self.received_response = False
        self.connect_poll_timer = QTimer(self)
        self.connect_poll_timer.setInterval(250)
        self.connect_poll_timer.timeout.connect(self.poll_connection)

    def generate_port_layout(self):
        portLayout = DHBoxLayout()
        portLayout.setColor(c.highlight)
        portLayout.addWidget(QLabel("Port:"))
        self.combo = QComboBox()
        portLayout.addWidget(self.combo)
        self.refresh_button = QPushButton("🔄 Refresh")
        self.refresh_button.clicked.connect(self.refresh_ports)
        portLayout.addWidget(self.refresh_button)
        self.status_label = QLabel("🔌 Disconnected")
        portLayout.addWidget(self.status_label)
        return portLayout

    def generate_connection_layout(self):
        connectionLayout = DHBoxLayout()
        connectionLayout.setColor(c.tertiary)
        for name, slot in [
            ("Connect", self.connect_serial),
            ("Disconnect", self.disconnect_serial),
        ]:
            b = QPushButton(name)
            b.clicked.connect(slot)
            connectionLayout.addWidget(b)
        self.poll_toggle = QPushButton("Polling On")
        self.poll_toggle.setCheckable(True)
        self.poll_toggle.setChecked(True)
        self.poll_toggle.clicked.connect(self.toggle_polling)
        connectionLayout.addWidget(self.poll_toggle)
        self.session_toggle = QPushButton("Quiet Tags")
        self.session_toggle.setCheckable(True)
        self.session_toggle.setChecked(False)
        self.session_toggle.toggled.connect(self.toggle_session)
        connectionLayout.addWidget(self.session_toggle)
        return connectionLayout

    def generate_shortcuts_layout(self):
        shortcutsLayout = DHBoxLayout()
        shortcutsLayout.setColor(c.secondary)
        for txt, cmd in [
            ("Version", ".vr"),
            ("Battery", ".bl"),
            ("Inventory", ".iv"),
        ]:
            btn = QPushButton(txt)
            btn.clicked.connect(lambda _, c=cmd: self.send_command(c))
            shortcutsLayout.addWidget(btn)
        b_sim = QPushButton("Simulator")
        b_sim.clicked.connect(self.open_simulator)
        shortcutsLayout.addWidget(b_sim)
        return shortcutsLayout

    def generate_log_layout(self):
        logLayout = DVBoxLayout()
        logLayout.setColor(c.highlight)
        self.log = QTextEdit(readOnly=True)
        logLayout.addWidget(self.log)
        b_clear = QPushButton("Clear Console")
        b_clear.clicked.connect(self.clear_console)
        logLayout.addWidget(b_clear)
        return logLayout

    def generate_table_layout(self):
        tableLayout = DVBoxLayout()
        tableLayout.setColor(c.secondary)
        b_clear_table = QPushButton("Clear Tags"); b_clear_table.clicked.connect(self.clear_table)
        tableLayout.addWidget(b_clear_table)

        self.tag_counts, self.tag_strengths, self.tag_min_strengths, self.tag_max_strengths = {}, {}, {}, {}
        self.strength_history_len = STRENGTH_HISTORY_LEN
        self.pending_tag = self.selected_tag = self.search_tag = None; self.search_tag_seen = False

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tag","Count","Min Strength","Max Strength"])
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # user-resizable for all

        # --- Stretch-first-column behavior (interactive) ---
        def _stretch_first():
            tot = self.table.viewport().width()
            others = sum(self.table.columnWidth(i) for i in range(1, self.table.columnCount()))
            w = max(120, tot - others - 2)  # min width; tweak as needed
            self.table.setColumnWidth(0, w)

        class _EF(QObject):  # resize event filter
            def __init__(self, cb, parent=None): super().__init__(parent); self.cb=cb
            def eventFilter(self, obj, ev): 
                if ev.type()==QEvent.Resize: self.cb()
                return False

        self._tbl_ef = _EF(_stretch_first, self.table)
        self.table.installEventFilter(self._tbl_ef)              # table resized
        self.table.viewport().installEventFilter(self._tbl_ef)   # viewport resized
        header.sectionResized.connect(lambda *_: _stretch_first())  # any column changed
        _stretch_first()  # initial fit
        # --- end stretch-first-column ---

        tableLayout.addWidget(self.table, 1)
        return tableLayout

    def generate_tag_search_layout(self):
        tagSearchLayout = DHBoxLayout()
        tagSearchLayout.setColor(c.highlight)
        tagSearchLayout.addWidget(QLabel("Search Tag:"))
        self.tag_search_input = QLineEdit()
        self.tag_search_input.setPlaceholderText("Enter tag")
        self.tag_search_input.textChanged.connect(self.on_search_tag_changed)
        tagSearchLayout.addWidget(self.tag_search_input)
        return tagSearchLayout
    
    def generate_command_layout(self):
        commandLayout = DHBoxLayout()
        commandLayout.setColor(c.tertiary)
        commandLayout.addWidget(QLabel("Command:"))
        self.input = QLineEdit()
        commandLayout.addWidget(self.input)
        b_send = QPushButton("Send")
        b_send.clicked.connect(lambda: self.send_command(self.input.text()))
        commandLayout.addWidget(b_send)
        return commandLayout

    def generate_version_layout(self):
        versionLayout = DVBoxLayout()
        versionLayout.setColor(c.tertiary)
        versionLayout.addWidget(QLabel("Version"))
        self.version_bar = QProgressBar()
        self.version_bar.setTextVisible(False)
        self.version_bar.setFixedHeight(4)
        self.version_bar.setStyleSheet(
            """
            QProgressBar {border:1px solid #555;border-radius:2px;background:#eee;}
            QProgressBar::chunk {background-color:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #66f,stop:1 #9cf);}
            """
        )
        versionLayout.addWidget(self.version_bar)
        self.version_display = QTextEdit(readOnly=True)
        versionLayout.addWidget(self.version_display)
        return versionLayout

    def generate_battery_layout(self):
            batteryLayout = DVBoxLayout()
            batteryLayout.setColor(c.secondary)
            batteryLayout.addWidget(QLabel("Battery"))
            self.battery_bar = QProgressBar()
            self.battery_bar.setTextVisible(False)
            self.battery_bar.setFixedHeight(4)
            self.battery_bar.setStyleSheet(
                """
                QProgressBar {border:1px solid #555;border-radius:2px;background:#eee;}
                QProgressBar::chunk {background-color:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #66f,stop:1 #9cf);}
                """
            )
            batteryLayout.addWidget(self.battery_bar)
            self.battery_display = QTextEdit(readOnly=True)
            batteryLayout.addWidget(self.battery_display)
            return batteryLayout

    def generate_plot_layout(self):
            plotLayout = DVBoxLayout()
            plotLayout.setColor(c.tertiary)
            plotLayout.addWidget(QLabel("Signal Strength"))
            self.strength_canvas = MplCanvas()
            plotLayout.addWidget(self.strength_canvas)
            return plotLayout

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
        """Rescan available serial ports without blocking the UI."""
        if hasattr(self, "refresh_button"):
            self.refresh_button.setText("🔄 Refreshing")
            self.refresh_button.setEnabled(False)

        threading.Thread(target=self._refresh_ports_worker, daemon=True).start()

    def _refresh_ports_worker(self):
        ports = serial.tools.list_ports.comports()
        usb = []
        bt = []
        for p in ports:
            if "usbserial" in p.device:
                usb.append(p)
            else:
                bt.append(p)

        if self.worker:
            self.worker.stop()
            self.worker = None

        # Schedule the UI update back on the main thread. When QTimer.singleShot
        # is invoked without a receiver from a worker thread, the timer lives in
        # that thread and never fires because there's no event loop. Passing
        # `self` as the receiver ensures the callback executes in the GUI thread.
        QTimer.singleShot(0, self, lambda: self._update_ports_ui(usb, bt, ports))

    def _update_ports_ui(self, usb, bt, ports):
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

        self.combo.setCurrentIndex(-1)
        for i in range(self.combo.count()):
            if self.combo.itemData(i):
                self.combo.setCurrentIndex(i)
                break

        if hasattr(self, "refresh_button"):
            self.refresh_button.setText("🔄 Refresh")
            self.refresh_button.setEnabled(True)

    def connect_serial(self):
        """Create and start the worker for the chosen port."""
        port = self.combo.currentData()
        if not port or self.worker:
            return
        self.auto_reconnect = True
        self.worker = SerialWorker(port)
        self.worker.connected.connect(self.on_port_opened)
        self.worker.disconnected.connect(self.on_disconnected)
        self.worker.line_received.connect(self.process_line)
        self.worker.command_sent.connect(self.on_command_sent)
        self.worker.start()

    def disconnect_serial(self):
        """Stop the worker and reset the UI."""
        if self.worker:
            self.auto_reconnect = False
            # Tell the reader we're disconnecting so it can sleep
            self.send_command(".sl", silent=True)
            self.worker.stop()
            self.worker = None
        self.reconnecting = False
        self.awaiting_vr = False
        self.received_response = False
        self.connect_poll_timer.stop()
        self.pending_port = None
        self.progress = 0
        self.version_bar.setValue(0)
        self.battery_bar.setValue(0)
        self.scanning = False
        self.pending_tag = None
        self.status_label.setText("🔌 Disconnected")

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

    def poll_connection(self):
        """Rapidly poll for a version response while connecting."""
        if not self.worker or not self.awaiting_vr or self.received_response:
            self.connect_poll_timer.stop()
            return
        self.send_command(".vr", silent=True)

    def clear_console(self):
        """Clear the log output area."""
        self.log.clear()

    def clear_table(self) -> None:
        """Remove all tags from the table and reset history."""
        self.tag_counts.clear()
        self.tag_strengths.clear()
        self.tag_min_strengths.clear()
        self.tag_max_strengths.clear()

    def open_simulator(self) -> None:
        """Show the simulator window for manual line entry."""
        if self.simulator is None:
            self.simulator = SimulatorWindow(self)
        self.simulator.show()
        self.simulator.raise_()

    def send_command(self, cmd: str, silent: bool = False):
        """Send a command string to the reader."""
        cmd = cmd.strip()
        if not cmd:
            return

        if not self.worker:
            if not silent:
                self.status_label.setText("⚠️ Not connected")
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

    def on_port_opened(self, port: str) -> None:
        """Verify reader connectivity before finalizing connection."""
        self.status_label.setText("🔄 Connecting")
        self.pending_port = port
        self.awaiting_vr = True
        self.received_response = False
        self.send_command(".vr", silent=True)
        self.connect_poll_timer.start()

    def on_connected(self, port: str):
        """Handle reader connection."""
        self.status_label.setText(f"✅ Connected")
        self.connect_poll_timer.stop()
        if not self.reconnecting:
            self.tag_counts.clear()
            self.tag_strengths.clear()
            self.update_table()
            self.update_strength_plot()
        self.send_inventory_setup()
        self.scanning = True
        if self.poll_enabled:
            self.poll_status()
        self.reconnecting = False

    def on_disconnected(self):
        """Handle reader disconnection."""
        if self.auto_reconnect:
            self.status_label.setText("🔄 Reconnecting")
        else:
            self.status_label.setText("🔌 Disconnected")
        self.progress = 0
        self.version_bar.setValue(0)
        self.battery_bar.setValue(0)
        self.scanning = False
        self.pending_tag = None
        self.awaiting_vr = False
        self.received_response = False
        self.pending_port = None
        self.connect_poll_timer.stop()
        worker = self.worker
        self.worker = None
        if worker:
            worker.wait()
            worker.deleteLater()
        if self.auto_reconnect:
            self.reconnecting = True
            QTimer.singleShot(1000, self.connect_serial)

    def on_command_sent(self, cmd: str):
        """Log sent commands that aren't silent."""
        if self.silent_queue and self.silent_queue[0] == cmd:
            return
        self.log.append(f">> {cmd}")

    def process_line(self, line: str):
        """Process a single line of reader output."""
        if self.awaiting_vr and not self.received_response:
            self.received_response = True
            self.connect_poll_timer.stop()
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

        if resp.command == ".vr" and self.awaiting_vr:
            self.awaiting_vr = False
            if self.pending_port:
                self.on_connected(self.pending_port)
                self.pending_port = None

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

    def on_search_tag_changed(self, text: str) -> None:
        """Handle changes to the tag search input."""
        self.search_tag = text.strip().lstrip('0') or None
        self.search_tag_seen = False
        self.update_search_tag_color()

    def update_search_tag_color(self) -> None:
        """Update background color based on search tag status."""
        if not self.search_tag:
            self.tag_search_input.setStyleSheet("")
        elif self.search_tag_seen:
            self.tag_search_input.setStyleSheet(f"background-color: {c.green};")
        else:
            self.tag_search_input.setStyleSheet(f"background-color: {c.red};")

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
            tag = line[3:].strip().lstrip('0') 
            if not tag:
                return
            self.pending_tag = tag
            if self.search_tag and tag == self.search_tag:
                self.search_tag_seen = True
                self.update_search_tag_color()
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

class SimulatorWindow(QMainWindow):
    """Window for simulating reader output."""

    def __init__(self, main_window: "MainWindow") -> None:
        super().__init__()
        self.main_window = main_window
        self.setWindowTitle("Simulator")
        root = DVBoxLayout()
        root.noMargins()
        self.setCentralWidget(root._frame)

        tag_layout = DHBoxLayout()
        tag_layout.addWidget(QLabel("Tag:"))
        self.tag_input = QLineEdit()
        tag_layout.addWidget(self.tag_input)
        b_tag = QPushButton("Simulate Tag")
        b_tag.clicked.connect(self.simulate_tag)
        tag_layout.addWidget(b_tag)
        tag_layout.attachTo(root)

        log_layout = DVBoxLayout()
        log_layout.setColor(c.highlight)
        self.log = QTextEdit(readOnly=True)
        log_layout.addWidget(self.log)
        log_layout.attachTo(root, 1)

    def simulate_tag(self) -> None:
        tag = self.tag_input.text().strip()
        if not tag:
            return
        self.log.append(f"<< EP:{tag}")
        self.main_window.process_line(f"EP:{tag}")
        self.log.append("<< RI:50")
        self.main_window.process_line("RI:50")

    def closeEvent(self, e):
        self.main_window.simulator = None
        super().closeEvent(e)

def main() -> None:
    """Launch the GUI application."""
    app = QApplication(sys.argv)
    mw = MainWindow()
    mw.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
