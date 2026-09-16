"""Упаковывает исходный логотип в многоразмерный Windows ICO, без перерисовки."""
from pathlib import Path
import struct

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def build_icon(source: Path, destination: Path) -> None:
    logo = QImage(str(source))
    if logo.isNull():
        raise ValueError(f'Не удалось прочитать логотип: {source}')
    frames = []
    for size in ICON_SIZES:
        frame = QImage(size, size, QImage.Format.Format_ARGB32)
        frame.fill(Qt.GlobalColor.transparent)
        fitted = logo.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(frame)
        painter.drawImage((size - fitted.width()) // 2, (size - fitted.height()) // 2, fitted)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not frame.save(buffer, 'PNG'):
            raise OSError(f'Не удалось подготовить размер значка {size}')
        frames.append(bytes(buffer.data()))
    # ICONDIR + ICONDIRENTRY; значение 0 в поле размера означает 256 пикселей.
    offset = 6 + 16 * len(frames)
    entries = []
    for size, payload in zip(ICON_SIZES, frames, strict=True):
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(payload), offset))
        offset += len(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(struct.pack('<HHH', 0, 1, len(frames)) + b''.join(entries) + b''.join(frames))


if __name__ == '__main__':
    target = ROOT / 'app' / 'resources' / 'icons' / 'magiclab.ico'
    build_icon(ROOT / 'app' / 'resources' / 'images' / 'logo.png', target)
    print(f'Windows ICO: {target}; sizes: {ICON_SIZES}')
