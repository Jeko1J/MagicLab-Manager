from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select

from app.models import CAR_CLASS_LABELS, Customer, Order, OrderStatus, Vehicle
from app.repositories.customers import CustomerRepository
from app.repositories.orders import OrderRepository
from app.ui.dialogs.entity_dialogs import CustomerDialog, VehicleDialog
from app.ui.pages.base import Page
from app.ui.widgets import configure_table, format_datetime, format_money, status_item, table_item, plural, set_empty_text


class CustomersPage(Page):
    open_order = Signal(int)

    def __init__(self, database, parent=None) -> None:
        super().__init__(database, "Клиенты", parent)
        add = QPushButton("Новый клиент")
        add.setObjectName("primary")
        add.clicked.connect(self.add_customer)
        self.header.addWidget(add)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Быстрый поиск по телефону или имени")
        self.search.setClearButtonEnabled(True)
        self.root.addWidget(self.search)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 12, 0)
        self.customers = QTableWidget(0, 3)
        self.customers.setHorizontalHeaderLabels(("Имя", "Телефон", "Автомобили"))
        configure_table(self.customers)
        self.customers.setColumnWidth(1, 152)
        self.customers.setColumnWidth(2, 100)
        self.customers.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.customers)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 0, 0, 0)
        detail_actions = QHBoxLayout()
        self.detail_title = QLabel("Выберите клиента")
        self.detail_title.setObjectName("sectionTitle")
        self.edit_button = QPushButton("Редактировать")
        self.vehicle_button = QPushButton("Добавить автомобиль")
        right_layout.addWidget(self.detail_title)
        detail_actions.addWidget(self.edit_button)
        detail_actions.addWidget(self.vehicle_button)
        detail_actions.addStretch()
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        vehicles_title = QLabel("Автомобили")
        vehicles_title.setObjectName("sectionTitle")
        self.vehicles = QTableWidget(0, 4)
        self.vehicles.setHorizontalHeaderLabels(("Автомобиль", "Гос. номер", "Класс", "Цвет"))
        configure_table(self.vehicles)
        self.vehicles.setColumnWidth(1, 105)
        self.vehicles.setColumnWidth(2, 168)
        self.vehicles.setColumnWidth(3, 84)
        self.vehicles.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        history_title = QLabel("История заказов")
        history_title.setObjectName("sectionTitle")
        self.orders = QTableWidget(0, 4)
        self.orders.setHorizontalHeaderLabels(("Номер", "Дата", "Стоимость", "Статус"))
        configure_table(self.orders)
        self.orders.setColumnWidth(1, 155)
        self.orders.setColumnWidth(2, 100)
        self.orders.setColumnWidth(3, 116)
        self.orders.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        right_layout.addLayout(detail_actions)
        right_layout.addWidget(self.summary)
        right_layout.addWidget(vehicles_title)
        right_layout.addWidget(self.vehicles, 1)
        right_layout.addWidget(history_title)
        right_layout.addWidget(self.orders, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 680])
        self.root.addWidget(splitter, 1)
        self.search.textChanged.connect(self.refresh)
        self.customers.itemSelectionChanged.connect(self.load_details)
        self.edit_button.clicked.connect(self.edit_customer)
        self.vehicle_button.clicked.connect(self.add_vehicle)
        self.orders.doubleClicked.connect(self._open_order)
        self.vehicles.doubleClicked.connect(self.edit_vehicle)
        self.edit_button.setEnabled(False)
        self.vehicle_button.setEnabled(False)
        set_empty_text(self.customers, 'Клиенты не найдены. Измените поиск или нажмите «Новый клиент».')
        set_empty_text(self.vehicles, 'Автомобилей пока нет.')
        set_empty_text(self.orders, 'История заказов пуста.')

    def selected_customer_id(self) -> int | None:
        if self.customers.currentRow() < 0:
            return None
        item = self.customers.item(self.customers.currentRow(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def refresh(self) -> None:
        selected_id = self.selected_customer_id()
        with self.database.session() as session:
            customers = CustomerRepository(session).search(self.search.text())
            rows = [(item.id, item.full_name, item.phone, len(item.vehicles)) for item in customers]
        self.customers.setRowCount(len(rows))
        selected_row = -1
        for row, (customer_id, name, phone, vehicle_count) in enumerate(rows):
            self.customers.setItem(row, 0, table_item(name, customer_id))
            self.customers.setItem(row, 1, table_item(phone))
            self.customers.setItem(row, 2, table_item(str(vehicle_count), alignment=Qt.AlignmentFlag.AlignCenter))
            if customer_id == selected_id:
                selected_row = row
        if selected_row >= 0:
            self.customers.selectRow(selected_row)
        elif rows:
            self.customers.selectRow(0)
        else:
            self.clear_details()
        if rows:
            self.load_details()

    def clear_details(self) -> None:
        self.detail_title.setText("Выберите клиента")
        self.summary.clear()
        self.vehicles.setRowCount(0)
        self.vehicles.setFixedHeight(110)
        self.orders.setRowCount(0)
        self.edit_button.setEnabled(False)
        self.vehicle_button.setEnabled(False)

    def load_details(self) -> None:
        customer_id = self.selected_customer_id()
        if not customer_id:
            self.clear_details()
            return
        with self.database.session() as session:
            customer = CustomerRepository(session).by_id(customer_id)
            if customer is None:
                return
            name, phone, comment = customer.full_name, customer.phone, customer.comment
            vehicles = [(v.id, v.brand, v.model, v.license_plate, v.car_class, v.color) for v in customer.vehicles]
            orders = OrderRepository(session).search()
            orders = [item for item in orders if item.customer_id == customer_id]
            total = CustomerRepository(session).completed_total(customer_id)
        self.detail_title.setText(name)
        self.summary.setWordWrap(True)
        self.detail_title.setWordWrap(True)
        self.summary.setText(f"{phone}  ·  {plural(len(orders), ('обращение', 'обращения', 'обращений'))}  ·  завершено на {format_money(total)}" + (f'\n{comment}' if comment else ''))
        self.vehicles.setRowCount(len(vehicles))
        self.vehicles.setFixedHeight(min(180, max(110, 36 * len(vehicles) + 40)))
        for row, (vehicle_id, brand, model, plate, car_class, color) in enumerate(vehicles):
            self.vehicles.setItem(row, 0, table_item(f"{brand} {model}", vehicle_id))
            self.vehicles.setItem(row, 1, table_item(plate))
            self.vehicles.setItem(row, 2, table_item(CAR_CLASS_LABELS[car_class]))
            self.vehicles.setItem(row, 3, table_item(color or "—"))
        self.orders.setRowCount(len(orders))
        for row, order in enumerate(orders):
            self.orders.setItem(row, 0, table_item(order.public_number, order.id))
            self.orders.setItem(row, 1, table_item(format_datetime(order.scheduled_at)))
            self.orders.setItem(row, 2, table_item(format_money(order.total_price), alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            self.orders.setItem(row, 3, status_item(order.status))
        self.edit_button.setEnabled(True)
        self.vehicle_button.setEnabled(True)

    def add_customer(self) -> None:
        dialog = CustomerDialog(self.database, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_customer(self) -> None:
        customer_id = self.selected_customer_id()
        if customer_id and CustomerDialog(self.database, customer_id, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def add_vehicle(self) -> None:
        customer_id = self.selected_customer_id()
        if customer_id and VehicleDialog(self.database, customer_id, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _open_order(self) -> None:
        if self.orders.currentRow() >= 0:
            item = self.orders.item(self.orders.currentRow(), 0)
            if item:
                self.open_order.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def edit_vehicle(self) -> None:
        item = self.vehicles.item(self.vehicles.currentRow(), 0)
        if item and self.selected_customer_id():
            dialog = VehicleDialog(self.database, self.selected_customer_id(), int(item.data(Qt.ItemDataRole.UserRole)), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.load_details()

