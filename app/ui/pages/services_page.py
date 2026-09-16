from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from app.ui.styles import COLORS
from PySide6.QtWidgets import QHeaderView, QMessageBox, QPushButton, QTableWidget

from app.models import CarClass
from app.repositories.services import ServiceRepository
from app.ui.dialogs.entity_dialogs import ServiceDialog
from app.ui.pages.base import Page
from app.ui.widgets import configure_table, format_duration, format_money, table_item, set_empty_text
from app.services.access_service import require_database, can


class ServicesPage(Page):
    def __init__(self, database, parent=None) -> None:
        actor = require_database(database, 'services_view')
        super().__init__(database, "Услуги", parent)
        add = QPushButton("Добавить услугу")
        add.setObjectName("primary")
        add.clicked.connect(self.add_service)
        self.header.addWidget(add)
        add.setVisible(can(actor, 'services_edit'))
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels((
            "Название", "Категория", "Время", "Легковой", "Кроссовер",
            "Внедорожник", "Минивэн", "Состояние",
        ))
        configure_table(self.table, sortable=True)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(5, 115)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        if can(actor, 'services_edit'):
            self.table.doubleClicked.connect(self.edit_service)
        self.table.sortItems(0, Qt.SortOrder.AscendingOrder)
        set_empty_text(self.table, 'Каталог пуст. Нажмите «Добавить услугу» и укажите цены для классов автомобиля.')
        self.root.addWidget(self.table, 1)
        actions = self.root
        self.toggle_button = QPushButton("Отключить услугу")
        self.toggle_button.setEnabled(False)
        self.table.itemSelectionChanged.connect(self.update_toggle_button)
        self.toggle_button.clicked.connect(self.toggle_service)
        self.header.addWidget(self.toggle_button)
        self.toggle_button.setVisible(can(actor, 'services_edit'))

    def selected_id(self) -> int | None:
        if self.table.currentRow() < 0:
            return None
        item = self.table.item(self.table.currentRow(), 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def refresh(self) -> None:
        with self.database.session() as session:
            services = ServiceRepository(session).all(True)
            rows = []
            for service in services:
                prices = {p.car_class: p.price for p in service.prices}
                rows.append((service.id, service.name, service.category, service.duration_minutes, prices, service.is_active))
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row, (service_id, name, category, duration, prices, active) in enumerate(rows):
            self.table.setItem(row, 0, table_item(name, service_id))
            self.table.setItem(row, 1, table_item(category))
            self.table.setItem(row, 2, table_item(format_duration(duration), sort_value=duration))
            for column, car_class in enumerate(CarClass, 3):
                self.table.setItem(row, column, table_item(format_money(prices.get(car_class, 0)), alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, sort_value=float(prices.get(car_class, 0))))
            state = table_item("Активна" if active else "Отключена")
            state.setData(Qt.ItemDataRole.UserRole, active)
            state.setForeground(QColor(COLORS['text'] if active else COLORS['muted']))
            self.table.setItem(row, 7, state)
        self.table.setSortingEnabled(sorting)
        self.update_toggle_button()

    def update_toggle_button(self):
        state = self.table.item(self.table.currentRow(), 7)
        self.toggle_button.setEnabled(state is not None)
        self.toggle_button.setText('Восстановить услугу' if state and not state.data(Qt.ItemDataRole.UserRole) else 'Отключить услугу')

    def add_service(self) -> None:
        require_database(self.database, 'services_edit')
        if ServiceDialog(self.database, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_service(self) -> None:
        require_database(self.database, 'services_edit')
        service_id = self.selected_id()
        if service_id and ServiceDialog(self.database, service_id, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def toggle_service(self) -> None:
        require_database(self.database, 'services_edit')
        service_id = self.selected_id()
        if not service_id:
            QMessageBox.information(self, "Услуги", "Выберите услугу в таблице")
            return
        with self.database.session() as session:
            repository = ServiceRepository(session)
            service = repository.by_id(service_id)
            if service is None:
                return
            if service.is_active:
                repository.disable(service_id)
            else:
                repository.enable(service_id)
            session.commit()
        self.refresh()


from PySide6.QtWidgets import QDialog
