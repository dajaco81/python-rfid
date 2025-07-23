#!/usr/bin/env python3
"""
Robust PyQt5 TSL 1128 GUI with clean Connect/Disconnect
"""
import sys, serial, serial.tools.list_ports, re
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
    QPushButton, QComboBox, QLineEdit, QTextEdit, QHBoxLayout,
    QVBoxLayout, QTableWidget, QTableWidgetItem)
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

    def write(s, cmd: str):
        if s.ser and s.ser.is_open:
            for p in cmd.split(';'):
                s.ser.write((p+"\r\n").encode())
                s.data_received.emit(f">> {p}")

    def stop(s):
        s._running = False  # signal thread to exit; actual close in run()
        s.wait()            # block until the thread has fully shut down

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TSL 1128 Interface"); self.resize(800,600)
        w=QWidget(); self.setCentralWidget(w); l=QVBoxLayout(w)
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
        # Auto‑poll every 10 seconds
        self.timer=QTimer(self); self.timer.timeout.connect(self.poll_status)
        self.timer.start(10000)
        self.worker=None; self.refresh_ports()

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
        for cmd in (".vr", ".bl"): self.send_command(cmd)

    def send_command(self, cmd: str):
        cmd=cmd.strip()
        if not cmd: return
        if not self.worker:
            self.log.append("⚠️ Not connected"); return
        self.log.append(f">> {cmd}"); self.worker.write(cmd)
        self.input.clear()

    def process_data(self, text):
        self.log.append(text)
        if text.startswith("<< "):
            line = text[3:]
            if ':' not in line and re.fullmatch(r'[0-9A-Fa-f]+', line.strip()):
                t=line.strip()
                self.tag_counts[t]=self.tag_counts.get(t,0)+1
                self.update_table()

    def update_table(self):
        self.table.setRowCount(len(self.tag_counts))
        for r,(t,c) in enumerate(self.tag_counts.items()):
            self.table.setItem(r,0,QTableWidgetItem(t))
            self.table.setItem(r,1,QTableWidgetItem(str(c)))

    def closeEvent(self, e):
        if self.worker: self.worker.stop()
        e.accept()

if __name__=="__main__":
    app=QApplication(sys.argv)
    mw=MainWindow(); mw.show()
    sys.exit(app.exec_())
