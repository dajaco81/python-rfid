#!/usr/bin/env python3
"""
Robust PyQt5 TSL 1128 GUI with clean Connect/Disconnect
"""
import sys, serial, serial.tools.list_ports, re
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
    QPushButton, QComboBox, QLineEdit, QTextEdit, QHBoxLayout,
    QVBoxLayout, QTableWidget, QTableWidgetItem, QDial)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer

class SerialWorker(QThread):
    data_received = pyqtSignal(str)
    def __init__(s, port, baud=115200):
        super().__init__(); s.port=port; s.baud=baud; s._running=True; s.ser=None

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
                    parts = buf.split('\r\n'); buf = parts.pop()
                    for line in parts:
                        s.data_received.emit(f"<< {line}")
        finally:
            if s.ser and s.ser.is_open:
                s.ser.close()
                s.data_received.emit("🔌 Disconnected")

    def write(s, cmd: str, echo=True):
        if s.ser and s.ser.is_open:
            for p in cmd.split(';'):
                s.ser.write((p+"\r\n").encode())
                if echo:
                    s.data_received.emit(f">> {p}")

    def stop(s):
        s._running = False  # signal thread to exit; actual close in run()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TSL 1128 Interface"); self.resize(800,600)
        w=QWidget(); self.setCentralWidget(w)
        root=QHBoxLayout(w)
        l=QVBoxLayout(); root.addLayout(l,1)
        r=QVBoxLayout(); root.addLayout(r)
        # Port selector + Refresh
        h1=QHBoxLayout(); h1.addWidget(QLabel("Port:"))
        self.combo=QComboBox(); h1.addWidget(self.combo)
        bR=QPushButton("🔄 Refresh"); bR.clicked.connect(self.refresh_ports)
        h1.addWidget(bR); l.addLayout(h1)
        # Connect/Disconnect/Poll
        h0=QHBoxLayout()
        for name,slot in [("Connect",self.connect_serial),
                          ("Disconnect",self.disconnect_serial),
                          ("Poll Status",self.poll_status)]:
            b=QPushButton(name); b.clicked.connect(slot); h0.addWidget(b)
        l.addLayout(h0)
        # Shortcuts
        h2=QHBoxLayout()
        for txt,cmd in [("Version",".vr"),("Battery",".bl"),("Inventory",".ec on;.iv;.ec off")]:
            btn=QPushButton(txt); btn.clicked.connect(lambda _,c=cmd:self.send_command(c))
            h2.addWidget(btn)
        l.addLayout(h2)
        # Manual
        h3=QHBoxLayout(); h3.addWidget(QLabel("Command:"))
        self.input=QLineEdit(); h3.addWidget(self.input)
        bS=QPushButton("Send"); bS.clicked.connect(lambda:self.send_command(self.input.text()))
        h3.addWidget(bS); l.addLayout(h3)
        # Log + Table
        self.log=QTextEdit(readOnly=True); l.addWidget(self.log)
        self.tag_counts={}; self.table=QTableWidget(0,2)
        self.table.setHorizontalHeaderLabels(["Tag","Count"]); l.addWidget(self.table)
        # Right side info containers
        r.addWidget(QLabel("Version"))
        self.version_display=QTextEdit(readOnly=True); r.addWidget(self.version_display)
        r.addWidget(QLabel("Battery"))
        self.battery_display=QTextEdit(readOnly=True); r.addWidget(self.battery_display)
        r.addWidget(QLabel("Next poll"))
        self.dial=QDial(); self.dial.setNotchesVisible(False)
        r.addWidget(self.dial)
        # Auto‑poll
        self.poll_interval=10
        self.countdown=self.poll_interval
        self.dial.setRange(0,self.poll_interval)
        self.dial.setValue(self.poll_interval)
        self.timer=QTimer(self); self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)
        self.worker=None; self.refresh_ports()
        self.silent_counter=0
        self.current_cmd=None
        self.version_info={}; self.battery_info={}

    def refresh_ports(self):
        ports=serial.tools.list_ports.comports(); self.combo.clear()
        for p in ports: self.combo.addItem(f"{p.device} — {p.description}", p.device)
        if not ports: self.combo.addItem("<no ports>", "")
        self.log.append(f"🔄 Ports: {[self.combo.itemText(i) for i in range(self.combo.count())]}")
        if self.worker: self.worker.stop(); self.worker=None

    def connect_serial(self):
        port=self.combo.currentData()
        if not port or self.worker: return
        self.worker=SerialWorker(port); self.worker.data_received.connect(self.process_data)
        self.worker.start()

    def disconnect_serial(self):
        if self.worker: self.worker.stop(); self.worker=None

    def poll_status(self):
        for cmd in (".vr", ".bl"):
            self.send_command(cmd, silent=True)
        self.countdown=self.poll_interval

    def send_command(self, cmd: str, silent=False):
        cmd=cmd.strip()
        if not cmd:
            return
        if not self.worker:
            if not silent:
                self.log.append("⚠️ Not connected")
            return
        if not silent:
            self.log.append(f">> {cmd}")
        else:
            self.silent_counter += len(cmd.split(';'))
        self.worker.write(cmd, echo=not silent)
        self.input.clear()

    def process_data(self, text):
        silent = self.silent_counter > 0
        if not silent:
            self.log.append(text)
        if text.startswith("<< "):
            line = text[3:]
            self.parse_line(line)
            if silent and (line == "OK:" or line.startswith("ER:")):
                self.silent_counter -= 1
            if not silent and ':' not in line and re.fullmatch(r'[0-9A-Fa-f]+', line.strip()):
                t=line.strip()
                self.tag_counts[t]=self.tag_counts.get(t,0)+1
                self.update_table()

    def update_table(self):
        self.table.setRowCount(len(self.tag_counts))
        for r,(t,c) in enumerate(self.tag_counts.items()):
            self.table.setItem(r,0,QTableWidgetItem(t))
            self.table.setItem(r,1,QTableWidgetItem(str(c)))

    def parse_line(self, line: str):
        if line.startswith("CS:"):
            self.current_cmd = line[4:].strip()
        elif line == "OK:" or line.startswith("ER:"):
            self.current_cmd = None
        elif self.current_cmd == ".vr":
            if ':' in line:
                k,v = line.split(':',1)
                self.version_info[k.strip()] = v.strip()
                self.update_version_display()
        elif self.current_cmd == ".bl":
            if ':' in line:
                k,v = line.split(':',1)
                self.battery_info[k.strip()] = v.strip()
                self.update_battery_display()

    def update_version_display(self):
        txt = '\n'.join(f"{k}: {v}" for k,v in self.version_info.items())
        self.version_display.setPlainText(txt)

    def update_battery_display(self):
        txt = '\n'.join(f"{k}: {v}" for k,v in self.battery_info.items())
        self.battery_display.setPlainText(txt)

    def update_countdown(self):
        self.dial.setValue(self.countdown)
        self.countdown -= 1
        if self.countdown < 0:
            self.poll_status()

    def closeEvent(self, e):
        if self.worker: self.worker.stop()
        e.accept()

if __name__=="__main__":
    app=QApplication(sys.argv)
    mw=MainWindow(); mw.show()
    sys.exit(app.exec_())
