from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget, QSizePolicy


class Page(QWidget):
    def __init__(self, database, title: str, parent=None) -> None:
        from app.services.access_service import require_database
        permissions = {'Главная': 'statistics', 'Статистика': 'statistics', 'Заказы': 'orders',
                       'Расписание': 'orders', 'Клиенты': 'customers', 'Услуги': 'services_view',
                       'Настройки': 'account', 'Мои заказы': 'master_orders', 'Пользователи': 'users', 'Журнал действий': 'audit'}
        require_database(database, permissions.get(title, 'account'))
        super().__init__(parent)
        self.database = database
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 16, 20, 16)
        self.root.setSpacing(10)
        self.header = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("pageTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.header.addWidget(self.title)
        self.header.addStretch()
        self.root.addLayout(self.header)
