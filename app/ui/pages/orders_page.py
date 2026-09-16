from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QSettings, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
)

from app.config import APP_NAME, ORGANIZATION_NAME
from app.models import CAR_CLASS_LABELS, ORDER_STATUS_LABELS, CarClass, OrderStatus
from app.repositories.orders import OrderRepository
from app.ui.pages.base import Page
from app.ui.widgets import configure_table, format_datetime, format_money, status_item, table_item, set_empty_text


class OrdersPage(Page):
    new_order = Signal()
    open_order = Signal(int)

    def __init__(self, database, parent=None) -> None:
        super().__init__(database, "Заказы", parent)
        add = QPushButton("Новый заказ")
        add.setObjectName("primary")
        add.clicked.connect(self.new_order)
        self.header.addWidget(add)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Номер, клиент, телефон, марка или гос. номер")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(660)
        self.status = QComboBox()
        self.status.addItem("Все статусы", None)
        for value, label in ORDER_STATUS_LABELS.items():
            self.status.addItem(label, value)
        self.car_class = QComboBox()
        self.car_class.addItem("Все классы", None)
        for value, label in CAR_CLASS_LABELS.items():
            self.car_class.addItem(label, value)
        self.date_mode = QComboBox()
        self.date_mode.addItem("Все даты", "all")
        self.date_mode.addItem("Сегодня", "today")
        self.date_mode.addItem("Выбранная дата", "selected")
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setEnabled(False)
        reset = QPushButton("Сбросить фильтры")
        reset.clicked.connect(self.reset_filters)
        self.header.insertWidget(1, self.search, 1)
        self.header.setStretch(2, 1)
        filters.addWidget(self.status)
        filters.addWidget(self.car_class)
        filters.addWidget(self.date_mode)
        filters.addWidget(self.date_edit)
        filters.addWidget(reset)
        filters.addStretch()
        for field, width in ((self.status, 200), (self.car_class, 196), (self.date_mode, 168), (self.date_edit, 140)):
            field.setFixedWidth(width)
        self.root.addLayout(filters)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(("Номер", "Дата и время", "Клиент", "Автомобиль", "Гос. номер", "Стоимость", "Статус"))
        configure_table(self.table, sortable=True)
        for column, width in enumerate((145, 156, 220, 220, 110, 112, 128)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.open_selected)
        self.root.addWidget(self.table, 1)
        self.search.textChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        self.car_class.currentIndexChanged.connect(self.refresh)
        self.date_mode.currentIndexChanged.connect(self._date_mode_changed)
        self.date_edit.dateChanged.connect(self.refresh)
        self.settings = QSettings(ORGANIZATION_NAME, APP_NAME)
        self.restore_column_widths()

    def _date_mode_changed(self) -> None:
        self.date_edit.setEnabled(self.date_mode.currentData() == "selected")
        self.refresh()

    def reset_filters(self) -> None:
        self.search.clear()
        self.status.setCurrentIndex(0)
        self.car_class.setCurrentIndex(0)
        self.date_mode.setCurrentIndex(0)
        self.date_edit.setDate(QDate.currentDate())
        self.refresh()

    def selected_id(self) -> int | None:
        if self.table.currentRow() < 0:
            return None
        item = self.table.item(self.table.currentRow(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def open_selected(self) -> None:
        order_id = self.selected_id()
        if order_id:
            self.open_order.emit(order_id)

    def show_context_menu(self, position) -> None:
        if not self.table.itemAt(position):
            return
        menu = QMenu(self)
        action = QAction("Открыть карточку", self)
        action.triggered.connect(self.open_selected)
        menu.addAction(action)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def refresh(self) -> None:
        mode = self.date_mode.currentData()
        selected_date = None
        if mode == "today":
            selected_date = date.today()
        elif mode == "selected":
            selected_date = self.date_edit.date().toPython()
        with self.database.session() as session:
            orders = OrderRepository(session).search(
                self.search.text(), self.status.currentData(), selected_date, selected_date, self.car_class.currentData()
            )
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            self.table.setItem(row, 0, table_item(order.public_number, order.id))
            self.table.setItem(row, 1, table_item(format_datetime(order.scheduled_at), sort_value=order.scheduled_at.timestamp()))
            self.table.setItem(row, 2, table_item(order.customer.full_name))
            self.table.setItem(row, 3, table_item(f"{order.vehicle.brand} {order.vehicle.model}"))
            self.table.setItem(row, 4, table_item(order.vehicle.license_plate))
            self.table.setItem(row, 5, table_item(format_money(order.total_price), alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, sort_value=float(order.total_price)))
            self.table.setItem(row, 6, status_item(order.status))
        self.table.setSortingEnabled(sorting)
        filtered = bool(self.search.text() or self.status.currentData() or self.car_class.currentData() or mode != 'all')
        set_empty_text(self.table, 'Заказы не найдены. Измените поиск или сбросьте фильтры.' if filtered else 'Заказов пока нет. Нажмите «Новый заказ», чтобы оформить запись.')

    def restore_column_widths(self) -> None:
        for column in range(self.table.columnCount()):
            value = self.settings.value(f"orders/compact_column_{column}")
            if value:
                self.table.setColumnWidth(column, int(value))

    def save_column_widths(self) -> None:
        for column in range(self.table.columnCount()):
            self.settings.setValue(f"orders/compact_column_{column}", self.table.columnWidth(column))
