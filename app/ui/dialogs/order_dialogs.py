from __future__ import annotations

import csv
import html
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDateTime, QMarginsF, Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextDocument, QPdfWriter, QPageSize
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QMenu,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import EXPORT_DIR
from app.models import (
    ALLOWED_STATUS_TRANSITIONS,
    CAR_CLASS_LABELS,
    ORDER_STATUS_LABELS,
    Customer,
    Order,
    OrderStatus,
    Service,
    Vehicle,
)
from app.repositories.orders import OrderRepository
from app.services.calculation_service import CalculationLine, calculate
from app.services.order_service import OrderService, OrderValidationError
from app.ui.dialogs.entity_dialogs import CustomerDialog, VehicleDialog
from app.ui.widgets import configure_table, format_datetime, format_duration, format_money, table_item, fit_to_screen, ErrorLabel, set_invalid, set_empty_text, status_item, WrappedComboBox
from app.ui.styles import STATUS_COLORS
from app.services.access_service import require_database, require
from app.services.audit_service import record_event
from app.services.user_service import UserService


class OrderDialog(QDialog):
    def __init__(self, database, order_id: int | None = None, parent=None) -> None:
        require_database(database, 'orders')
        super().__init__(parent)
        self.database = database
        self.order_id = order_id
        self.result_id: int | None = None
        self._loading = False
        self._services: dict[int, dict] = {}
        self._initial_state = ""
        self.setWindowTitle("Редактирование заказа" if order_id else "Новый заказ")
        self.setModal(True)
        self.resize(1160, 680)
        self.setMinimumSize(1020, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        title = QLabel("Редактирование заказа" if order_id else "Новый заказ")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 12, 0)
        left_layout.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(8)

        customer_row = QHBoxLayout()
        self.customer = WrappedComboBox()
        self.customer.setMinimumWidth(160)
        self.add_customer_button = QPushButton("Новый клиент")
        customer_row.addWidget(self.customer, 1)
        customer_row.addWidget(self.add_customer_button)
        form.addRow(QLabel("Клиент *"))
        form.addRow(customer_row)
        self.phone_label = QLabel("—")
        form.addRow("Телефон", self.phone_label)

        vehicle_row = QHBoxLayout()
        self.vehicle = WrappedComboBox()
        self.add_vehicle_button = QPushButton("Новый автомобиль")
        vehicle_row.addWidget(self.vehicle, 1)
        vehicle_row.addWidget(self.add_vehicle_button)
        form.addRow(QLabel("Автомобиль *"))
        form.addRow(vehicle_row)

        self.car_class = QLabel("—")
        self.car_class.setObjectName("muted")
        form.addRow("Класс автомобиля", self.car_class)
        self.scheduled_at = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.scheduled_at.setDisplayFormat("dd.MM.yyyy, HH:mm")
        self.scheduled_at.setCalendarPopup(True)
        form.addRow("Дата и время *", self.scheduled_at)
        self.master = QComboBox()
        self.master.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.master.addItem('Не назначен', None)
        with database.session() as session:
            for master in UserService(session).masters():
                self.master.addItem(master.full_name, master.id)
        form.addRow('Мастер', self.master)
        self.comment = QPlainTextEdit()
        self.comment.setPlaceholderText("Пожелания клиента и особенности работ")
        self.comment.setFixedHeight(84)
        form.addRow(QLabel("Комментарий"))
        form.addRow(self.comment)
        left_layout.addLayout(form)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 0, 0, 0)
        right_layout.setSpacing(10)
        services_title = QLabel("Услуги")
        services_title.setObjectName("sectionTitle")
        right_layout.addWidget(services_title)
        self.services_table = QTableWidget(0, 4)
        self.services_table.setHorizontalHeaderLabels(("", "Услуга", "Стоимость", "Время"))
        configure_table(self.services_table)
        self.services_table.horizontalHeader().setMinimumSectionSize(36)
        self.services_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.services_table.setColumnWidth(0, 36)
        self.services_table.setColumnWidth(2, 120)
        self.services_table.setColumnWidth(3, 95)
        right_layout.addWidget(self.services_table, 1)
        totals = QFormLayout()
        totals.setSpacing(8)
        self.total_price = QLabel("0 ₽")
        self.total_price.setObjectName("metricValue")
        self.total_duration = QLabel("0 мин")
        self.prepayment = QDoubleSpinBox()
        self.prepayment.setRange(0, 100_000_000)
        self.prepayment.setDecimals(2)
        self.prepayment.setSuffix(" ₽")
        self.balance = QLabel("0 ₽")
        totals.addRow("Общая стоимость", self.total_price)
        totals.addRow("Продолжительность", self.total_duration)
        totals.addRow("Предоплата", self.prepayment)
        totals.addRow("Остаток", self.balance)
        left_layout.addSpacing(4)
        left_layout.addLayout(totals)
        left_layout.addStretch()
        set_empty_text(self.services_table, 'Нет доступных услуг. Добавьте или включите услугу в каталоге.')

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([380, 740])
        root.addWidget(splitter, 1)
        self.error_label = ErrorLabel()
        root.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = QPushButton("Сохранить")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.customer.currentIndexChanged.connect(lambda _index: self.load_vehicles())
        self.vehicle.currentIndexChanged.connect(self.recalculate)
        self.services_table.itemChanged.connect(self.recalculate)
        self.prepayment.valueChanged.connect(self.recalculate)
        self.add_customer_button.clicked.connect(self.add_customer)
        self.add_vehicle_button.clicked.connect(self.add_vehicle)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save)
        self.load_customers()
        self.load_services()
        if order_id:
            self.load_order(order_id)
        self._initial_state = self.current_state()
        fit_to_screen(self)

    def load_customers(self, select_id: int | None = None) -> None:
        self._loading = True
        current_id = select_id if select_id is not None else self.customer.currentData()
        self.customer.clear()
        with self.database.session() as session:
            customers = list(session.scalars(select(Customer).order_by(Customer.full_name)))
        self.customer.addItem("Выберите клиента", None)
        for item in customers:
            self.customer.addItem(item.full_name, item.id)
        index = self.customer.findData(current_id)
        self.customer.setCurrentIndex(max(index, 0))
        self._loading = False
        self.load_vehicles()

    def load_vehicles(self, select_id: int | None = None) -> None:
        if self._loading:
            return
        self._loading = True
        current_id = select_id if select_id is not None else self.vehicle.currentData()
        customer_id = self.customer.currentData()
        self.vehicle.clear()
        self.vehicle.addItem("Выберите автомобиль", None)
        self.phone_label.setText("—")
        if customer_id:
            with self.database.session() as session:
                selected_customer = session.get(Customer, customer_id)
                self.phone_label.setText(selected_customer.phone if selected_customer else "—")
                vehicles = list(
                    session.scalars(select(Vehicle).where(Vehicle.customer_id == customer_id).order_by(Vehicle.brand, Vehicle.model))
                )
            for item in vehicles:
                self.vehicle.addItem(f"{item.brand} {item.model} — {item.license_plate}", item.id)
        index = self.vehicle.findData(current_id)
        self.vehicle.setCurrentIndex(max(index, 0))
        self.add_vehicle_button.setEnabled(bool(customer_id) and not bool(self.order_id))
        self._loading = False
        self.recalculate()

    def load_services(self) -> None:
        self._loading = True
        with self.database.session() as session:
            snapshots = {}
            if self.order_id:
                order = OrderRepository(session).by_id(self.order_id)
                if order:
                    snapshots = {item.service_id: item for item in order.items}
            services = list(
                session.scalars(
                    select(Service).options(selectinload(Service.prices)).where(
                        Service.is_active.is_(True) | Service.id.in_(snapshots)
                    ).order_by(Service.category, Service.name)
                ).unique()
            )
            data = [
                {
                    "id": service.id,
                    "name": snapshots[service.id].service_name_snapshot if service.id in snapshots else service.name,
                    "duration": snapshots[service.id].duration_snapshot if service.id in snapshots else service.duration_minutes,
                    "prices": {price.car_class: Decimal(snapshots[service.id].price_snapshot if service.id in snapshots else price.price) for price in service.prices},
                }
                for service in services
            ]
        self._services = {item["id"]: item for item in data}
        self.services_table.setRowCount(len(data))
        for row, item in enumerate(data):
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            checkbox.setCheckState(Qt.CheckState.Unchecked)
            checkbox.setData(Qt.ItemDataRole.UserRole, item["id"])
            self.services_table.setItem(row, 0, checkbox)
            self.services_table.setItem(row, 1, table_item(item["name"]))
            self.services_table.setItem(row, 2, table_item("—", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            self.services_table.setItem(row, 3, table_item(format_duration(item["duration"])))
        self._loading = False
        self.recalculate()

    def selected_service_ids(self) -> list[int]:
        result = []
        for row in range(self.services_table.rowCount()):
            item = self.services_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                result.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return result

    def current_vehicle_class(self):
        vehicle_id = self.vehicle.currentData()
        if not vehicle_id:
            return None
        with self.database.session() as session:
            vehicle = session.get(Vehicle, vehicle_id)
            return vehicle.car_class if vehicle else None

    def recalculate(self, *_args) -> None:
        if self._loading:
            return
        self.error_label.clear()
        for field in (self.customer, self.vehicle, self.services_table, self.prepayment):
            set_invalid(field, False)
        self.services_table.blockSignals(True)
        car_class = self.current_vehicle_class()
        self.car_class.setText(CAR_CLASS_LABELS.get(car_class, "—"))
        lines = []
        for row in range(self.services_table.rowCount()):
            check = self.services_table.item(row, 0)
            if check is None:
                continue
            service = self._services[int(check.data(Qt.ItemDataRole.UserRole))]
            price = service["prices"].get(car_class) if car_class else None
            price_item = self.services_table.item(row, 2)
            price_item.setText(format_money(price) if price is not None else "—")
            if check.checkState() == Qt.CheckState.Checked and price is not None:
                lines.append(CalculationLine(service["id"], service["name"], price, service["duration"]))
        result = calculate(lines)
        self.total_price.setText(format_money(result.total_price))
        self.total_duration.setText(format_duration(result.total_duration_minutes))
        balance = max(Decimal("0"), result.total_price - Decimal(str(self.prepayment.value())))
        self.balance.setText(format_money(balance))
        self.services_table.blockSignals(False)

    def add_customer(self) -> None:
        dialog = CustomerDialog(self.database, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_customers(dialog.result_id)

    def add_vehicle(self) -> None:
        customer_id = self.customer.currentData()
        if not customer_id:
            self.error_label.setText("Сначала выберите клиента")
            return
        dialog = VehicleDialog(self.database, customer_id, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_vehicles(dialog.result_id)

    def load_order(self, order_id: int) -> None:
        with self.database.session() as session:
            order = OrderRepository(session).by_id(order_id)
            if order is None:
                return
            customer_id = order.customer_id
            vehicle_id = order.vehicle_id
            scheduled = order.scheduled_at
            selected = {item.service_id for item in order.items}
            prepayment = float(order.prepayment)
            comment = order.comment
            master_id = order.assigned_master_id
            if master_id and self.master.findData(master_id) < 0:
                self.master.addItem(f'{order.assigned_master.full_name} (недоступен)', master_id)
        self._loading = True
        self.customer.setCurrentIndex(self.customer.findData(customer_id))
        self._loading = False
        self.load_vehicles(vehicle_id)
        self.scheduled_at.setDateTime(QDateTime(scheduled))
        self.prepayment.setValue(prepayment)
        self.comment.setPlainText(comment)
        self.master.setCurrentIndex(max(0, self.master.findData(master_id)))
        self._loading = True
        for row in range(self.services_table.rowCount()):
            item = self.services_table.item(row, 0)
            if int(item.data(Qt.ItemDataRole.UserRole)) in selected:
                item.setCheckState(Qt.CheckState.Checked)
        self._loading = False
        self.customer.setEnabled(False)
        self.vehicle.setEnabled(False)
        self.add_customer_button.setEnabled(False)
        self.add_vehicle_button.setEnabled(False)
        self.recalculate()

    def current_state(self) -> str:
        return "|".join(
            [
                str(self.customer.currentData()), str(self.vehicle.currentData()),
                self.scheduled_at.dateTime().toString(Qt.DateFormat.ISODate),
                ",".join(map(str, self.selected_service_ids())),
                str(self.prepayment.value()), self.comment.toPlainText(),
                str(self.master.currentData()),
            ]
        )

    def reject(self) -> None:
        if self._initial_state and self.current_state() != self._initial_state:
            answer = QMessageBox.question(
                self, "Несохранённые изменения", "Закрыть форму без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        super().reject()

    def save(self) -> None:
        for field in (self.customer, self.vehicle, self.services_table, self.prepayment):
            set_invalid(field, False)
        customer_id = self.customer.currentData()
        vehicle_id = self.vehicle.currentData()
        if not customer_id:
            self.error_label.setText("Выберите клиента")
            set_invalid(self.customer)
            self.customer.setFocus()
            return
        if not vehicle_id:
            self.error_label.setText("Выберите или добавьте автомобиль")
            set_invalid(self.vehicle)
            self.vehicle.setFocus()
            return
        if not self.selected_service_ids():
            self.error_label.setText("Выберите хотя бы одну услугу")
            set_invalid(self.services_table)
            self.services_table.setFocus()
            return
        try:
            with self.database.session() as session:
                service = OrderService(session)
                if self.order_id:
                    order = OrderRepository(session).by_id(self.order_id)
                    if order is None:
                        raise OrderValidationError("Заказ не найден")
                    service.update_order(
                        order,
                        self.scheduled_at.dateTime().toPython(),
                        self.selected_service_ids(), self.prepayment.value(),
                        self.comment.toPlainText(),
                        assigned_master_id=self.master.currentData(),
                    )
                else:
                    customer = session.get(Customer, customer_id)
                    vehicle = session.get(Vehicle, vehicle_id)
                    if customer is None or vehicle is None:
                        raise OrderValidationError("Клиент или автомобиль не найден")
                    order = service.create_order(
                        customer, vehicle, self.scheduled_at.dateTime().toPython(),
                        self.selected_service_ids(), self.prepayment.value(),
                        self.comment.toPlainText(),
                        assigned_master_id=self.master.currentData(),
                    )
                session.commit()
                self.result_id = order.id
        except ValueError as exc:
            self.error_label.setText(str(exc))
            if 'предоплат' in str(exc).lower():
                set_invalid(self.prepayment)
                self.prepayment.setFocus()
            return
        self._initial_state = self.current_state()
        self.accept()


class ChangeStatusDialog(QDialog):
    def __init__(self, current: OrderStatus, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Изменение статуса")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = QLabel('Изменение статуса')
        heading.setObjectName('pageTitle')
        layout.addWidget(heading)
        form = QFormLayout()
        self.status = QComboBox()
        for value in OrderStatus:
            if value not in ALLOWED_STATUS_TRANSITIONS[current]:
                continue
            self.status.addItem(ORDER_STATUS_LABELS[value], value)
        self.comment = QPlainTextEdit()
        self.comment.setPlaceholderText("Комментарий к изменению (необязательно)")
        self.comment.setMaximumHeight(90)
        form.addRow("Новый статус", self.status)
        form.addRow("Комментарий", self.comment)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        apply_button = QPushButton("Изменить статус")
        apply_button.setObjectName("primary")
        buttons.addButton(apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def order_document_html(order: Order, inspection_html: str = '') -> str:
    rows = "".join(
        f"<tr><td>{html.escape(item.service_name_snapshot)}</td>"
        f"<td style='text-align:right'>{format_duration(item.duration_snapshot)}</td>"
        f"<td style='text-align:right'>{format_money(item.price_snapshot)}</td></tr>"
        for item in order.items
    )
    balance = Decimal(order.total_price) - Decimal(order.prepayment)
    comment = html.escape(order.comment or "—").replace("\n", "<br>")
    return f"""
    <html><head><style>
    body {{ font-family: 'Segoe UI', Arial; color:#16181d; font-size:10pt; }}
    h1 {{ font-size:18pt; margin-bottom:2px; }} h2 {{ font-size:12pt; margin-top:18px; }}
    .muted {{ color:#5d626c; }} table {{ width:100%; border-collapse:collapse; }}
    th, td {{ border-bottom:1px solid #c8cbd1; padding:7px 5px; }} th {{ text-align:left; background:#ececf1; }}
    .totals {{ margin-left:55%; width:45%; }} .sign {{ margin-top:45px; }}
    </style></head><body>
    <h1>Magic Lab Detailing</h1><div class='muted'>Заказ-наряд № {html.escape(order.public_number)}</div>
    <h2>Сведения о заказе</h2>
    <table width='100%' cellpadding='7'><tr><td width='26%'>Дата и время</td><td>{format_datetime(order.scheduled_at)}</td></tr>
    <tr><td>Клиент</td><td>{html.escape(order.customer.full_name)}</td></tr>
    <tr><td>Телефон</td><td>{html.escape(order.customer.phone)}</td></tr>
    <tr><td>Автомобиль</td><td>{html.escape(order.vehicle.brand)} {html.escape(order.vehicle.model)}, {html.escape(order.vehicle.license_plate)}</td></tr></table>
    <h2>Перечень работ</h2><table width='100%' cellpadding='7'><tr><th width='60%'>Услуга</th><th width='18%' style='text-align:right'>Время</th><th width='22%' style='text-align:right'>Стоимость</th></tr>{rows}</table>
    <table width='100%' cellpadding='7' class='totals'><tr><td>Итого</td><td style='text-align:right'><b>{format_money(order.total_price)}</b></td></tr>
    <tr><td>Предоплата</td><td style='text-align:right'>{format_money(order.prepayment)}</td></tr>
    <tr><td>Остаток</td><td style='text-align:right'><b>{format_money(balance)}</b></td></tr></table>
    <h2>Комментарий</h2><p>{comment}</p>
    <table width='100%' cellpadding='7' class='sign'><tr><td>Администратор ____________________</td><td>Клиент ____________________</td></tr></table>
    {inspection_html}</body></html>"""


def write_pdf(document: QTextDocument, path: str) -> None:
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15))
    writer.setResolution(144)
    document.print_(writer)
    del writer
    if not Path(path).is_file() or Path(path).stat().st_size == 0:
        raise OSError("Не удалось сохранить PDF")


class OrderDetailsDialog(QDialog):
    def __init__(self, database, order_id: int, parent=None) -> None:
        require_database(database, 'orders')
        super().__init__(parent)
        self.database = database
        self.order_id = order_id
        self.changed = False
        self.setWindowTitle("Карточка заказа")
        self.resize(1240, 700)
        self.setMinimumSize(880, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        order_page = QWidget()
        self.tabs.addTab(order_page, 'Заказ')
        self.root = QVBoxLayout(order_page)
        self.root.setContentsMargins(6, 10, 6, 6)
        self.root.setSpacing(10)
        self.header = QLabel()
        self.header.setObjectName("pageTitle")
        heading = QHBoxLayout()
        heading.addWidget(self.header)
        heading.addStretch()
        self.status_label = QLabel()
        heading.addWidget(self.status_label)
        self.summary = QWidget()
        summary_grid = QGridLayout(self.summary)
        summary_grid.setContentsMargins(0, 0, 0, 0)
        summary_grid.setHorizontalSpacing(16)
        summary_grid.setVerticalSpacing(6)
        self.summary_fields = {}
        for row, pair in enumerate((('Дата и время', 'Продолжительность'), ('Клиент', 'Телефон'), ('Автомобиль', 'Гос. номер'), ('Мастер', 'Ориентировочно готов'))):
            for col, caption in enumerate(pair):
                label = QLabel(caption)
                label.setObjectName('muted')
                value = QLabel()
                value.setWordWrap(True)
                value.setTextFormat(Qt.TextFormat.PlainText)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                summary_grid.addWidget(label, row, col * 2)
                summary_grid.addWidget(value, row, col * 2 + 1)
                self.summary_fields[caption] = value
        summary_grid.setColumnStretch(1, 3)
        summary_grid.setColumnStretch(3, 2)
        self.comment_label = QLabel()
        self.comment_label.setWordWrap(True)
        self.comment_label.setTextFormat(Qt.TextFormat.PlainText)
        self.comment_label.setObjectName('muted')
        self.totals_label = QLabel()
        self.totals_label.setTextFormat(Qt.TextFormat.RichText)
        self.items = QTableWidget(0, 3)
        self.items.setHorizontalHeaderLabels(("Услуга", "Продолжительность", "Стоимость"))
        configure_table(self.items)
        self.items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.items.setColumnWidth(1, 150)
        self.items.setColumnWidth(2, 140)
        history_title = QLabel("История статусов")
        history_title.setObjectName("sectionTitle")
        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(("Дата", "Предыдущий статус", "Новый статус", "Комментарий"))
        configure_table(self.history)
        self.history.setColumnWidth(0, 155)
        self.history.setColumnWidth(1, 168)
        self.history.setColumnWidth(2, 168)
        self.history.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.root.addLayout(heading)
        self.root.addWidget(self.summary)
        self.root.addWidget(self.comment_label)
        self.root.addWidget(self.items)
        self.root.addWidget(self.totals_label)
        self.root.addWidget(history_title)
        self.root.addWidget(self.history, 1)
        actions = QHBoxLayout()
        self.edit_button = QPushButton("Редактировать")
        self.status_button = QPushButton("Изменить статус")
        self.status_button.setObjectName('primary')
        documents_button = QPushButton('Документы')
        document_menu = QMenu(documents_button)
        document_menu.addAction('Печать заказ-наряда', self.print_preview)
        document_menu.addAction('Сохранить PDF', self.save_pdf)
        document_menu.addAction('Экспорт карточки в CSV', self.export_card)
        documents_button.setMenu(document_menu)
        self.cancel_button = QPushButton("Отменить заказ")
        self.cancel_button.setObjectName("danger")
        close_button = QPushButton("Закрыть")
        for button in (self.status_button, self.edit_button, documents_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        actions.addWidget(close_button)
        self.root.addLayout(actions)
        self.edit_button.clicked.connect(self.edit_order)
        self.status_button.clicked.connect(self.change_status)
        self.cancel_button.clicked.connect(self.cancel_order)
        close_button.clicked.connect(self.accept)
        self.load_data()
        from app.ui.dialogs.inspection_dialogs import InspectionPanel
        self.inspection_panel = InspectionPanel(database, order_id, self)
        self.tabs.addTab(self.inspection_panel, 'Осмотр ЛКП')
        self.inspection_panel.data_changed.connect(lambda: setattr(self, 'changed', True))
        self.inspection_panel.print_requested.connect(self.print_preview)
        self.inspection_panel.close_requested.connect(self.accept)
        with database.session() as session:
            order = self.get_order(session)
        if order:
            record_event(database, 'Просмотр заказа', 'Открыта карточка заказа', order.public_number)
        fit_to_screen(self)

    def get_order(self, session):
        return OrderRepository(session).by_id(self.order_id)

    def done(self, result):
        if hasattr(self, 'inspection_panel') and not self.inspection_panel.confirm_close():
            return
        super().done(result)

    def load_data(self) -> None:
        with self.database.session() as session:
            order = self.get_order(session)
            if order is None:
                return
            self.header.setText(f"Заказ {order.public_number}")
            balance = Decimal(order.total_price) - Decimal(order.prepayment)
            values = {'Дата и время': format_datetime(order.scheduled_at),
                      'Продолжительность': format_duration(order.total_duration_minutes),
                      'Клиент': order.customer.full_name, 'Телефон': order.customer.phone,
                      'Автомобиль': f'{order.vehicle.brand} {order.vehicle.model}',
                      'Гос. номер': order.vehicle.license_plate}
            from datetime import timedelta
            values['Мастер'] = order.assigned_master.full_name if order.assigned_master else 'Не назначен'
            values['Ориентировочно готов'] = format_datetime(order.scheduled_at + timedelta(minutes=order.total_duration_minutes))
            for caption, value in values.items():
                self.summary_fields[caption].setText(value)
            self.status_label.setText(ORDER_STATUS_LABELS[order.status])
            self.status_label.setStyleSheet(f'color: {STATUS_COLORS[order.status.value]};')
            self.comment_label.setText(f'Комментарий: {order.comment}' if order.comment else '')
            self.comment_label.setVisible(bool(order.comment))
            self.totals_label.setText(f'<b>Итого: {format_money(order.total_price)}</b>&nbsp;&nbsp; · &nbsp;&nbsp;Предоплата: {format_money(order.prepayment)}&nbsp;&nbsp; · &nbsp;&nbsp;<b>Остаток: {format_money(balance)}</b>')
            item_rows = [(i.service_name_snapshot, i.duration_snapshot, i.price_snapshot) for i in order.items]
            history_rows = [(h.changed_at, h.old_status, h.new_status, h.comment) for h in order.status_history]
            can_change = bool(ALLOWED_STATUS_TRANSITIONS[order.status])
            can_cancel = OrderStatus.CANCELLED in ALLOWED_STATUS_TRANSITIONS[order.status]
            can_edit = order.status not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED)
        self.items.setRowCount(len(item_rows))
        self.items.setFixedHeight(min(240, max(116, 36 * len(item_rows) + 40)))
        for row, (name, duration, price) in enumerate(item_rows):
            self.items.setItem(row, 0, table_item(name))
            self.items.setItem(row, 1, table_item(format_duration(duration)))
            self.items.setItem(row, 2, table_item(format_money(price), alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        self.history.setRowCount(len(history_rows))
        for row, (changed_at, old_status, new_status, comment) in enumerate(history_rows):
            self.history.setItem(row, 0, table_item(format_datetime(changed_at)))
            self.history.setItem(row, 1, status_item(old_status) if old_status else table_item('—'))
            self.history.setItem(row, 2, status_item(new_status))
            self.history.setItem(row, 3, table_item(comment or "—"))
        self.status_button.setEnabled(can_change)
        self.cancel_button.setVisible(can_cancel)
        self.edit_button.setEnabled(can_edit)

    def edit_order(self) -> None:
        dialog = OrderDialog(self.database, self.order_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.changed = True
            self.load_data()
            self.inspection_panel.refresh()

    def change_status(self) -> None:
        with self.database.session() as session:
            order = self.get_order(session)
            if order is None or not ALLOWED_STATUS_TRANSITIONS[order.status]:
                return
            current = order.status
        dialog = ChangeStatusDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.status.currentData() == OrderStatus.CANCELLED:
            if QMessageBox.question(self, "Отмена заказа", "Подтвердить отмену заказа?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        try:
            with self.database.session() as session:
                order = self.get_order(session)
                OrderService(session).change_status(order, dialog.status.currentData(), dialog.comment.toPlainText())
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось изменить статус", str(exc))
            return
        self.changed = True
        self.load_data()

    def cancel_order(self) -> None:
        answer = QMessageBox.warning(
            self, "Отмена заказа", "Отменить заказ? Действие будет записано в историю статусов.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with self.database.session() as session:
                order = self.get_order(session)
                OrderService(session).change_status(order, OrderStatus.CANCELLED, "Заказ отменён администратором")
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, "Не удалось отменить заказ", str(exc))
            return
        self.changed = True
        self.load_data()

    def _document(self) -> QTextDocument:
        require_database(self.database, 'documents')
        from app.ui.inspection_print import inspection_print_parts, add_image_resources
        with self.database.session() as session:
            order = self.get_order(session)
            inspection_html, resources = inspection_print_parts(session, self.order_id)
            source = order_document_html(order, inspection_html)
        document = QTextDocument(self)
        add_image_resources(document, resources)
        document.setHtml(source)
        return document

    def print_preview(self) -> None:
        require_database(self.database, 'documents')
        if not self.inspection_panel.confirm_close():
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        document = self._document()
        preview = QPrintPreviewDialog(printer, self)
        preview.setWindowTitle("Печать заказ-наряда")
        preview.paintRequested.connect(document.print_)
        preview.exec()
        with self.database.session() as session:
            number = self.get_order(session).public_number
        record_event(self.database, 'Печатная форма', 'Открыт диалог печати; факт физической печати не подтверждается', number)

    def save_pdf(self) -> None:
        require_database(self.database, 'documents')
        if not self.inspection_panel.confirm_close():
            return
        with self.database.session() as session:
            order = self.get_order(session)
            default = EXPORT_DIR / f"{order.public_number}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить заказ-наряд", str(default), "PDF (*.pdf)")
        if not path:
            return
        try:
            write_pdf(self._document(), path)
        except OSError:
            QMessageBox.warning(self, "Сохранение PDF", "Не удалось записать файл. Проверьте путь и права доступа.")
            return
        QMessageBox.information(self, "PDF сохранён", f"Файл сохранён:\n{path}")
        record_event(self.database, 'Экспорт PDF', 'Сохранён заказ-наряд PDF', order.public_number)

    def export_card(self) -> None:
        require_database(self.database, 'documents')
        with self.database.session() as session:
            order = self.get_order(session)
            default = EXPORT_DIR / f"{order.public_number}.csv"
            rows = [
                ("Номер", order.public_number), ("Дата", format_datetime(order.scheduled_at)),
                ("Клиент", order.customer.full_name), ("Телефон", order.customer.phone),
                ("Автомобиль", f"{order.vehicle.brand} {order.vehicle.model}"),
                ("Гос. номер", order.vehicle.license_plate), ("Статус", ORDER_STATUS_LABELS[order.status]),
                ("Стоимость", str(order.total_price)), ("Предоплата", str(order.prepayment)),
                ("Остаток", str(order.total_price - order.prepayment)),
                ("Продолжительность, мин", order.total_duration_minutes),
                ("Комментарий", order.comment),
            ]
            service_rows = [(item.service_name_snapshot, str(item.price_snapshot), item.duration_snapshot) for item in order.items]
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт карточки", str(default), "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerows(rows)
                writer.writerow([])
                writer.writerow(("Услуга", "Стоимость", "Продолжительность, мин"))
                writer.writerows(service_rows)
        except OSError:
            QMessageBox.warning(self, "Экспорт", "Не удалось записать выбранный файл")
            return
        QMessageBox.information(self, "Экспорт завершён", f"Файл сохранён:\n{path}")
        record_event(self.database, 'Экспорт карточки', 'Сохранена карточка CSV', order.public_number)
