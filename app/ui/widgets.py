from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from PySide6.QtCore import QEvent, QObject, Qt, Signal, QTimer, QRect, QSize, QPointF
from PySide6.QtGui import QColor, QTextLayout, QTextOption, QPixmap, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QApplication,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
    QWidget,
    QComboBox,
    QSizePolicy,
    QStyleOptionComboBox,
)

from app.models import ORDER_STATUS_LABELS, OrderStatus
from app.ui.styles import STATUS_COLORS
from app.config import RESOURCE_DIR


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logo = QPixmap(str(RESOURCE_DIR / 'images' / 'logo.png'))
        self.setFixedSize(144, 75)
        self.setAccessibleName('Magic Lab Detailing')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#17191F'))
        if self.logo.isNull():
            painter.setPen(QColor('#F2F3F5'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Magic Lab')
        else:
            # Убираем чёрную подложку, сохраняя цвета логотипа.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.rect(), self.logo)


class ErrorLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__('', parent)
        self.setObjectName('error')
        self.setWordWrap(True)
        self.hide()

    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))

    def clear(self):
        self.setText('')


def set_invalid(field, invalid=True):
    field.setProperty('invalid', invalid)
    field.style().unpolish(field)
    field.style().polish(field)


def set_empty_text(table, text):
    table._empty_controller.label.setText(text)


class WrappedComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(16)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.currentTextChanged.connect(self._fit_text)

    def _fit_text(self, *_args):
        bounds = self.fontMetrics().boundingRect(QRect(0, 0, max(80, self.width() - 40), 1000), Qt.TextFlag.TextWordWrap, self.currentText())
        self.setFixedHeight(max(34, bounds.height() + 12))
        self.setToolTip(self.currentText())
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_text()

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ''
        painter = QPainter(self)
        self.style().drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option, painter, self)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option, QStyle.SubControl.SC_ComboBoxEditField, self)
        painter.setPen(QColor('#F2F3F5' if self.isEnabled() else '#A6ACB8'))
        painter.drawText(rect.adjusted(2, 0, -4, 0), Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignVCenter, self.currentText())


def format_money(value) -> str:
    amount = Decimal(str(value or 0))
    if amount == amount.to_integral():
        return f"{int(amount):,}".replace(",", " ") + " ₽"
    return f"{amount:,.2f}".replace(",", " ") + " ₽"


def format_duration(minutes: int) -> str:
    hours, remainder = divmod(int(minutes or 0), 60)
    if hours and remainder:
        return f"{hours} ч {remainder} мин"
    if hours:
        return f"{hours} ч"
    return f"{remainder} мин"


def format_datetime(value: datetime) -> str:
    return value.strftime("%d.%m.%Y, %H:%M")


class SortableItem(QTableWidgetItem):
    def __lt__(self, other):
        left = self.data(Qt.ItemDataRole.UserRole + 1)
        right = other.data(Qt.ItemDataRole.UserRole + 1)
        if left is not None and right is not None:
            return left < right
        return self.text().casefold() < other.text().casefold()


class WrappingDelegate(QStyledItemDelegate):
    def text_layout(self, text, font, width, alignment):
        layout = QTextLayout(text, font)
        settings = QTextOption()
        settings.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        settings.setAlignment(alignment & (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignHCenter))
        layout.setTextOption(settings)
        layout.beginLayout()
        height = 0
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(25, width))
            line.setPosition(QPointF(0, height))
            height += line.height()
        layout.endLayout()
        return layout, height

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ''
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if not text:
            return
        from PySide6.QtGui import QPalette
        role = QPalette.ColorRole.HighlightedText if opt.state & QStyle.StateFlag.State_Selected else QPalette.ColorRole.Text
        painter.save()
        painter.setPen(opt.palette.color(role))
        painter.setFont(opt.font)
        layout, height = self.text_layout(text, opt.font, opt.rect.width() - 16, opt.displayAlignment)
        layout.draw(painter, QPointF(opt.rect.x() + 8, opt.rect.y() + max(4, (opt.rect.height() - height) / 2)))
        painter.restore()

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if not opt.text:
            return QSize(70, 36)
        table = self.parent()
        width = max(25, table.columnWidth(index.column()) - 16)
        _layout, height = self.text_layout(opt.text, opt.font, width, opt.displayAlignment)
        return QSize(width + 16, max(36, int(height) + 12))


def table_item(text: str, user_data=None, alignment=None, sort_value=None) -> QTableWidgetItem:
    item = SortableItem(text)
    item.setToolTip(text)
    if sort_value is not None:
        item.setData(Qt.ItemDataRole.UserRole + 1, sort_value)
    if user_data is not None:
        item.setData(Qt.ItemDataRole.UserRole, user_data)
    if alignment is not None:
        item.setTextAlignment(alignment)
    return item


def status_item(status: OrderStatus, order_id: int | None = None) -> QTableWidgetItem:
    short_labels = {
        OrderStatus.NEW: 'Новая заявка', OrderStatus.BOOKED: 'Записан',
        OrderStatus.IN_PROGRESS: 'В работе', OrderStatus.READY: 'Готов',
        OrderStatus.COMPLETED: 'Завершён', OrderStatus.CANCELLED: 'Отменён',
    }
    item = table_item(short_labels[status], order_id)
    item.setToolTip(ORDER_STATUS_LABELS[status])
    item.setForeground(QColor(STATUS_COLORS[status.value]))
    return item


def configure_table(table: QTableWidget, sortable: bool = False) -> None:
    table.setItemDelegate(WrappingDelegate(table))
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(sortable)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(36)
    table.horizontalHeader().setMinimumSectionSize(70)
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    table.setShowGrid(False)
    table.setWordWrap(True)
    table.setTextElideMode(Qt.TextElideMode.ElideNone)
    table._fit_pending = False
    controller = EmptyTableController(table)
    table._empty_controller = controller
    def schedule_fit(*_args):
        if table._fit_pending:
            return
        table._fit_pending = True
        QTimer.singleShot(0, fit)
    def fit():
        table._fit_pending = False
        table.resizeRowsToContents()
        for row in range(table.rowCount()):
            if table.rowHeight(row) < 36:
                table.setRowHeight(row, 36)
        for column in range(table.columnCount()):
            item, header = table.item(0, column), table.horizontalHeaderItem(column)
            if item and header:
                alignment = item.textAlignment()
                header.setTextAlignment(Qt.AlignmentFlag(alignment) if alignment else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
        controller.update()
    table.model().rowsInserted.connect(schedule_fit)
    table.model().rowsRemoved.connect(schedule_fit)
    table.model().dataChanged.connect(schedule_fit)
    table.horizontalHeader().sectionResized.connect(schedule_fit)


class EmptyTableController(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.table = table
        self.label = QLabel("Записей пока нет", table.viewport())
        self.label.setObjectName("muted")
        self.label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.label.setContentsMargins(16, 24, 16, 0)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        table.viewport().installEventFilter(self)
        self.update()

    def update(self):
        self.label.setGeometry(self.table.viewport().rect())
        self.label.setVisible(self.table.rowCount() == 0)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.update()
        return False


def plural(number: int, forms: tuple[str, str, str]) -> str:
    index = 2 if 11 <= number % 100 <= 14 else (0 if number % 10 == 1 else 1 if 2 <= number % 10 <= 4 else 2)
    return f"{number} {forms[index]}"


def fit_to_screen(widget) -> None:
    if QApplication.platformName() == 'offscreen':
        return
    screen = widget.screen()
    if screen is not None:
        rect = screen.availableGeometry()
        width, height = max(600, rect.width() - 24), max(450, rect.height() - 48)
        widget.setMinimumSize(min(widget.minimumWidth(), width), min(widget.minimumHeight(), height))
        widget.resize(min(widget.width(), width), min(widget.height(), height))


class MetricPanel(QFrame):
    def __init__(self, caption: str, value: str = "0", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 12, 8)
        layout.setSpacing(3)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        caption_label = QLabel(caption)
        caption_label.setObjectName("metricCaption")
        layout.addWidget(self.value_label)
        layout.addWidget(caption_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class UppercaseFilter(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyRelease and hasattr(watched, "text"):
            text = watched.text()
            upper = text.upper()
            if text != upper:
                position = watched.cursorPosition()
                watched.setText(upper)
                watched.setCursorPosition(position)
        return False
