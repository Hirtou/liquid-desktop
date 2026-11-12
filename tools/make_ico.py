"""Значок установщика и ярлыков: те же четыре плитки, что в трее виджетов. Пишет .ico (PNG внутри) без плагинов Qt.

    python tools/make_ico.py build/LiquidDesktop/liquid.ico
"""
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
frames = []
for size in (16, 24, 32, 48, 64, 128, 256):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    k = size / 64
    for i, color in enumerate(["#4b7bff", "#5ad1a0", "#ffc861", "#ff6b6b"]):
        p.setBrush(QColor(color))
        p.drawRoundedRect((4 + (i % 2) * 30) * k, (4 + (i // 2) * 30) * k, 26 * k, 26 * k, 6 * k, 6 * k)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    frames.append((size, bytes(data)))

out = struct.pack("<HHH", 0, 1, len(frames))
offset = 6 + 16 * len(frames)
for size, png in frames:
    out += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
    offset += len(png)
out += b"".join(png for _, png in frames)
with open(sys.argv[1], "wb") as f:
    f.write(out)
