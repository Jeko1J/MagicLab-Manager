from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCalendarWidget, QHBoxLayout, QHeaderView, QLabel, QSplitter, QTableWidget, QVBoxLayout, QWidget, QToolButton, QPushButton
from PySide6.QtGui import QColor, QTextCharFormat, QIcon
from app.config import RESOURCE_DIR

from app.repositories.orders import OrderRepository
from app.ui.pages.base import Page
from app.ui.widgets import configure_table, status_item, table_item, set_empty_text
from app.ui.dialogs.calendar_export_dialog import CalendarExportDialog


class SchedulePage(Page):
    open_order = Signal(int)

    def __init__(self, database, parent=None) -> None:
        super().__init__(database, "Расписание", parent)
        self.export_button = QPushButton('Экспорт в календарь')
        self.export_button.clicked.connect(self.export_calendar)
        self.header.addWidget(self.export_button)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        calendar_container = QWidget()
        calendar_layout = QVBoxLayout(calendar_container)
        calendar_layout.setContentsMargins(0, 0, 14, 0)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setMinimumWidth(280)
        self.calendar.setMaximumWidth(360)
        self.calendar.setFixedHeight(272)
        weekend = QTextCharFormat()
        weekend.setForeground(QColor('#B7BDC7'))
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend)
        self.calendar.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend)
        for name, icon in (('qt_calendar_prevmonth', 'chevron-left.svg'), ('qt_calendar_nextmonth', 'chevron-right.svg')):
            self.calendar.findChild(QToolButton, name).setIcon(QIcon(str(RESOURCE_DIR / 'icons' / icon)))
        calendar_layout.addWidget(self.calendar)
        calendar_layout.addStretch()
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(14, 0, 0, 0)
        self.date_title = QLabel()
        self.date_title.setObjectName("sectionTitle")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Время", "Клиент", "Автомобиль", "Услуги", "Статус"))
        configure_table(self.table)
        self.table.setColumnWidth(0, 75)
        self.table.setColumnWidth(4, 120)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        set_empty_text(self.table, 'На выбранную дату записей нет. Выберите другой день в календаре.')
        list_layout.addWidget(self.date_title)
        list_layout.addWidget(self.table, 1)
        splitter.addWidget(calendar_container)
        splitter.addWidget(list_container)
        splitter.setSizes([300, 800])
        self.root.addWidget(splitter, 1)
        self.calendar.selectionChanged.connect(self.refresh)
        self.table.doubleClicked.connect(self._open)

    def export_calendar(self):
        CalendarExportDialog(self.database, self.calendar.selectedDate(), self).exec()

    def _open(self) -> None:
        item = self.table.item(self.table.currentRow(), 0)
        if item:
            self.open_order.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def refresh(self) -> None:
        selected = self.calendar.selectedDate().toPython()
        self.date_title.setText(f"Записи на {selected.strftime('%d.%m.%Y')}")
        with self.database.session() as session:
            orders = OrderRepository(session).on_date(selected)
        self.table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            services = ", ".join(item.service_name_snapshot for item in order.items)
            self.table.setItem(row, 0, table_item(order.scheduled_at.strftime("%H:%M"), order.id))
            self.table.setItem(row, 1, table_item(order.customer.full_name))
            self.table.setItem(row, 2, table_item(f"{order.vehicle.brand} {order.vehicle.model}, {order.vehicle.license_plate}"))
            self.table.setItem(row, 3, table_item(services))
            self.table.setItem(row, 4, status_item(order.status))
