from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QMessageBox,
)

from app.models import CAR_CLASS_LABELS, CarClass, Customer, Service, ServicePrice, Vehicle
from app.repositories.customers import CustomerRepository
from app.services.order_service import OrderValidationError, normalize_phone, validate_customer_fields, validate_vehicle_fields
from app.ui.widgets import UppercaseFilter, ErrorLabel, set_invalid
from app.services.access_service import require_database


class FormDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(540)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 16, 20, 16)
        self.root.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName('pageTitle')
        self.root.addWidget(heading)
        self.error_label = ErrorLabel()
        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.root.addLayout(self.form)
        self._initial_state = None
        self._inline_error = None
        self._error_field = None

    def add_footer(self, text: str = "Сохранить") -> None:
        self.root.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = QPushButton(text)
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.root.addWidget(buttons)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save)
        self._initial_state = self.current_state()

    def current_state(self):
        values = [field.text() for field in self.findChildren(QLineEdit)]
        values += [field.toPlainText() for field in self.findChildren(QPlainTextEdit)]
        values += [str(field.currentIndex()) for field in self.findChildren(QComboBox)]
        values += [str(field.isChecked()) for field in self.findChildren(QCheckBox)]
        return tuple(values)

    def reject(self):
        if self._initial_state is not None and self.current_state() != self._initial_state:
            if QMessageBox.question(self, "Несохранённые изменения", "Закрыть форму без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        super().reject()

    def show_field_error(self, message, field=None):
        if self._error_field is not None:
            set_invalid(self._error_field, False)
        self._error_field = field
        self.error_label.setText(message)
        if self._inline_error is not None:
            self.form.removeRow(self._inline_error)
            self._inline_error = None
        if field is not None:
            set_invalid(field)
            row, _role = self.form.getWidgetPosition(field)
            if row >= 0:
                self._inline_error = QLabel(message)
                self._inline_error.setObjectName("error")
                self._inline_error.setWordWrap(True)
                self.form.insertRow(row + 1, "", self._inline_error)
                self.error_label.clear()
            field.setFocus()


class CustomerDialog(FormDialog):
    def __init__(self, database, customer_id: int | None = None, parent=None) -> None:
        require_database(database, 'customers')
        super().__init__("Клиент", parent)
        self.database = database
        self.customer_id = customer_id
        self.result_id: int | None = None
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("+7 (999) 123-45-67")
        self.comment = QPlainTextEdit()
        self.comment.setMaximumHeight(90)
        self.form.addRow("Имя *", self.name)
        self.form.addRow("Телефон *", self.phone)
        self.form.addRow("Комментарий", self.comment)
        if customer_id:
            with database.session() as session:
                item = session.get(Customer, customer_id)
                if item:
                    self.name.setText(item.full_name)
                    self.phone.setText(item.phone)
                    self.comment.setPlainText(item.comment)
        self.add_footer()

    def save(self) -> None:
        try:
            full_name, phone = validate_customer_fields(self.name.text(), self.phone.text())
            with self.database.session() as session:
                repo = CustomerRepository(session)
                if self.customer_id:
                    customer = repo.update(self.customer_id, full_name, phone, self.comment.toPlainText())
                else:
                    customer = repo.create(full_name, phone, self.comment.toPlainText())
                session.commit()
                self.result_id = customer.id
        except ValueError as exc:
            self.show_field_error(str(exc), self.name if not self.name.text().strip() else self.phone)
            return
        self.accept()


class VehicleDialog(FormDialog):
    def __init__(self, database, customer_id: int, vehicle_id: int | None = None, parent=None) -> None:
        require_database(database, 'customers')
        super().__init__("Автомобиль", parent)
        self.database = database
        self.customer_id = customer_id
        self.vehicle_id = vehicle_id
        self.result_id: int | None = None
        self.brand = QLineEdit()
        self.model = QLineEdit()
        self.plate = QLineEdit()
        self._uppercase_filter = UppercaseFilter(self)
        self.plate.installEventFilter(self._uppercase_filter)
        self.car_class = QComboBox()
        for value, label in CAR_CLASS_LABELS.items():
            self.car_class.addItem(label, value)
        self.color = QLineEdit()
        self.comment = QPlainTextEdit()
        self.comment.setMaximumHeight(80)
        self.form.addRow("Марка *", self.brand)
        self.form.addRow("Модель *", self.model)
        self.form.addRow("Гос. номер *", self.plate)
        self.form.addRow("Класс *", self.car_class)
        self.form.addRow("Цвет", self.color)
        self.form.addRow("Комментарий", self.comment)
        if vehicle_id:
            with database.session() as session:
                item = session.get(Vehicle, vehicle_id)
                if item:
                    self.brand.setText(item.brand)
                    self.model.setText(item.model)
                    self.plate.setText(item.license_plate)
                    self.car_class.setCurrentIndex(self.car_class.findData(item.car_class))
                    self.color.setText(item.color)
                    self.comment.setPlainText(item.comment)
        self.add_footer()

    def save(self) -> None:
        try:
            brand, model, plate = validate_vehicle_fields(self.brand.text(), self.model.text(), self.plate.text())
            with self.database.session() as session:
                if self.vehicle_id:
                    vehicle = CustomerRepository(session).update_vehicle(self.vehicle_id, brand, model, plate,
                        self.car_class.currentData(), self.color.text(), self.comment.toPlainText())
                else:
                    customer = session.get(Customer, self.customer_id)
                    if customer is None:
                        raise OrderValidationError("Клиент не найден")
                    vehicle = CustomerRepository(session).add_vehicle(
                        customer, brand, model, plate, self.car_class.currentData(),
                        self.color.text(), self.comment.toPlainText()
                    )
                session.commit()
                self.result_id = vehicle.id
        except ValueError as exc:
            if not self.brand.text().strip():
                field = self.brand
            elif not self.model.text().strip():
                field = self.model
            else:
                field = self.plate
            self.show_field_error(str(exc), field)
            return
        self.accept()


class ServiceDialog(FormDialog):
    def __init__(self, database, service_id: int | None = None, parent=None) -> None:
        require_database(database, 'services_edit')
        super().__init__("Услуга", parent)
        self.setMinimumWidth(660)
        self.database = database
        self.service_id = service_id
        self.name = QLineEdit()
        self.category = QLineEdit()
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(80)
        self.duration = QSpinBox()
        self.duration.setRange(1, 100_000)
        self.duration.setSuffix(" мин")
        self.active = QCheckBox("Услуга доступна для новых заказов")
        self.active.setChecked(True)
        self.prices: dict[CarClass, QDoubleSpinBox] = {}
        self.form.addRow("Название *", self.name)
        self.form.addRow("Категория *", self.category)
        self.form.addRow("Описание", self.description)
        self.form.addRow("Продолжительность *", self.duration)
        for car_class, label in CAR_CLASS_LABELS.items():
            field = QDoubleSpinBox()
            field.setRange(0, 100_000_000)
            field.setDecimals(2)
            field.setSuffix(" ₽")
            self.prices[car_class] = field
            self.form.addRow(f"Цена: {label}", field)
        self.form.addRow("", self.active)
        if service_id:
            with database.session() as session:
                from app.repositories.services import ServiceRepository
                item = ServiceRepository(session).by_id(service_id)
                if item:
                    self.name.setText(item.name)
                    self.category.setText(item.category)
                    self.description.setPlainText(item.description)
                    self.duration.setValue(item.duration_minutes)
                    self.active.setChecked(item.is_active)
                    for price in item.prices:
                        self.prices[price.car_class].setValue(float(price.price))
        self.add_footer()

    def save(self) -> None:
        if not self.name.text().strip():
            self.show_field_error("Введите название услуги", self.name)
            return
        if not self.category.text().strip():
            self.show_field_error("Введите категорию услуги", self.category)
            return
        try:
            with self.database.session() as session:
                from app.repositories.services import ServiceRepository
                ServiceRepository(session).save(self.service_id, self.name.text(), self.category.text(),
                    self.description.toPlainText(), self.duration.value(), self.active.isChecked(),
                    {key: field.value() for key, field in self.prices.items()})
                session.commit()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()
