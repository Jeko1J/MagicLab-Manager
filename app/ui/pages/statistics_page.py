from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDateEdit, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget

from app.models import ORDER_STATUS_LABELS, OrderStatus
from app.services.statistics_service import StatisticsService
from app.ui.pages.base import Page
from app.ui.widgets import MetricPanel, configure_table, format_money, status_item, table_item, set_empty_text


class StatisticsPage(Page):
    def __init__(self, database, parent=None) -> None:
        super().__init__(database, "Статистика", parent)
        filters = QHBoxLayout()
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_to = QDateEdit(QDate.currentDate())
        for field in (self.date_from, self.date_to):
            field.setCalendarPopup(True)
            field.setDisplayFormat("dd.MM.yyyy")
        apply_button = QPushButton("Показать")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self.refresh)
        filters.addWidget(QLabel("Период с"))
        filters.addWidget(self.date_from)
        filters.addWidget(QLabel("по"))
        filters.addWidget(self.date_to)
        filters.addWidget(apply_button)
        filters.addStretch()
        self.root.addLayout(filters)
        metrics = QGridLayout()
        self.created = MetricPanel("Создано заказов")
        self.completed = MetricPanel("Завершено")
        self.cancelled = MetricPanel("Отменено")
        self.revenue = MetricPanel("Предварительная выручка")
        self.average = MetricPanel("Средний чек")
        for index, metric in enumerate((self.created, self.completed, self.cancelled, self.revenue, self.average)):
            metrics.addWidget(metric, 0, index)
        self.root.addLayout(metrics)
        tables = QGridLayout()
        popular_title = QLabel("Популярные услуги")
        popular_title.setObjectName("sectionTitle")
        status_title = QLabel("Заказы по статусам")
        status_title.setObjectName("sectionTitle")
        self.popular = QTableWidget(0, 2)
        self.popular.setHorizontalHeaderLabels(("Услуга", "Количество"))
        configure_table(self.popular)
        set_empty_text(self.popular, 'За выбранный период нет заказанных услуг.')
        self.popular.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.statuses = QTableWidget(0, 2)
        self.statuses.setHorizontalHeaderLabels(("Статус", "Количество"))
        configure_table(self.statuses)
        self.statuses.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tables.addWidget(popular_title, 0, 0)
        tables.addWidget(status_title, 0, 1)
        tables.addWidget(self.popular, 1, 0)
        tables.addWidget(self.statuses, 1, 1)
        self.root.addLayout(tables, 1)

    def refresh(self) -> None:
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()
        if date_from > date_to:
            date_from, date_to = date_to, date_from
            self.date_from.setDate(QDate(date_from))
            self.date_to.setDate(QDate(date_to))
        with self.database.session() as session:
            result = StatisticsService(session).calculate(date_from, date_to)
        self.created.set_value(str(result.created))
        self.completed.set_value(str(result.completed))
        self.cancelled.set_value(str(result.cancelled))
        self.revenue.set_value(format_money(result.revenue))
        self.average.set_value(format_money(result.average_check))
        self.popular.setRowCount(len(result.popular_services))
        for row, (name, quantity) in enumerate(result.popular_services):
            self.popular.setItem(row, 0, table_item(name))
            self.popular.setItem(row, 1, table_item(str(quantity), alignment=Qt.AlignmentFlag.AlignCenter))
        self.statuses.setRowCount(len(OrderStatus))
        for row, status in enumerate(OrderStatus):
            self.statuses.setItem(row, 0, status_item(status))
            self.statuses.setItem(row, 1, table_item(str(result.status_counts[status]), alignment=Qt.AlignmentFlag.AlignCenter))
