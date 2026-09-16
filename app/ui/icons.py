from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def navigation_icon(index: int) -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#BFC5D0'), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    def line(x1, y1, x2, y2):
        painter.drawLine(QLineF(x1, y1, x2, y2))
    if index == 0:
        for x, y in ((4, 4), (14, 4), (4, 14), (14, 14)):
            painter.drawRoundedRect(QRectF(x, y, 6, 6), 1, 1)
    elif index == 1:
        painter.drawRoundedRect(QRectF(5, 3, 14, 18), 2, 2)
        for y in (8, 12, 16):
            line(9, y, 16, y)
    elif index == 2:
        painter.drawRoundedRect(QRectF(3, 5, 18, 16), 2, 2)
        line(3, 10, 21, 10)
        line(8, 3, 8, 7)
        line(16, 3, 16, 7)
        for x in (8, 15):
            line(x, 15, x+1, 15)
    elif index == 3:
        painter.drawEllipse(QRectF(8, 3, 8, 8))
        path = QPainterPath()
        path.moveTo(4, 21)
        path.cubicTo(4, 10, 20, 10, 20, 21)
        painter.drawPath(path)
    elif index == 4:
        painter.drawRoundedRect(QRectF(4, 4, 16, 16), 2, 2)
        line(8, 9, 16, 9)
        line(8, 14, 16, 14)
    elif index == 5:
        line(3, 3, 3, 21)
        line(3, 21, 21, 21)
        for x, y in ((7, 13), (12, 8), (17, 4)):
            painter.drawRect(QRectF(x, y, 3, 21-y))
    elif index == 6:
        for y, x in ((6, 8), (12, 16), (18, 10)):
            line(3, y, x-2, y)
            line(x+2, y, 21, y)
            painter.drawEllipse(QRectF(x-2, y-2, 4, 4))
    else:
        line(10, 3, 4, 3)
        line(4, 3, 4, 21)
        line(4, 21, 10, 21)
        line(9, 12, 21, 12)
        line(17, 8, 21, 12)
        line(17, 16, 21, 12)
    painter.end()
    return QIcon(pixmap)
