from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHeaderView, QLabel, QTableWidget
from sqlalchemy import func, select

from app.models import ORDER_STATUS_LABELS, Order, OrderStatus
from app.repositories.orders import OrderRepository
from app.services.statistics_service import StatisticsService
from app.ui.pages.base import Page
from app.ui.widgets import MetricPanel, configure_table, format_datetime, format_money, status_item, table_item, set_empty_text


class DashboardPage(Page):
    open_order = Signal(int)

    def __init__(self, database, parent=None) -> None:
        super().__init__(database, "Главная", parent)
        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        self.today_metric = MetricPanel("Заказы сегодня")
        self.progress_metric = MetricPanel("Автомобили в работе")
        self.ready_metric = MetricPanel("Автомобили готовы")
        self.revenue_metric = MetricPanel("Выручка за месяц")
        for index, metric in enumerate((self.today_metric, self.progress_metric, self.ready_metric, self.revenue_metric)):
            metrics.addWidget(metric, 0, index)
        self.root.addLayout(metrics)
        self.month_note = QLabel()
        self.month_note.setObjectName("muted")
        self.root.addWidget(self.month_note)
        content = QGridLayout()
        content.setHorizontalSpacing(14)
        content.setVerticalSpacing(8)
        upcoming_title = QLabel("Ближайшие записи")
        upcoming_title.setObjectName("sectionTitle")
        recent_title = QLabel("Последние изменения")
        recent_title.setObjectName("sectionTitle")
        statuses_title = QLabel("Распределение по статусам")
        statuses_title.setObjectName("sectionTitle")
        content.addWidget(upcoming_title, 0, 0)
        content.addWidget(statuses_title, 0, 1)
        self.upcoming = QTableWidget(0, 4)
        self.upcoming.setHorizontalHeaderLabels(("Дата", "Клиент", "Автомобиль", "Статус"))
        configure_table(self.upcoming)
        self.upcoming.setColumnWidth(0, 155)
        self.upcoming.setColumnWidth(3, 112)
        set_empty_text(self.upcoming, 'Предстоящих записей нет.')
        self.upcoming.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.upcoming.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.upcoming.doubleClicked.connect(self._open_from_upcoming)
        self.statuses = QTableWidget(0, 2)
        self.statuses.setHorizontalHeaderLabels(("Статус", "Заказов"))
        configure_table(self.statuses)
        self.statuses.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.statuses.setMaximumWidth(340)
        content.addWidget(self.upcoming, 1, 0)
        content.addWidget(self.statuses, 1, 1)
        content.addWidget(recent_title, 2, 0, 1, 2)
        self.recent = QTableWidget(0, 5)
        self.recent.setHorizontalHeaderLabels(("Номер", "Изменён", "Клиент", "Автомобиль", "Статус"))
        configure_table(self.recent)
        self.recent.setColumnWidth(0, 150)
        self.recent.setColumnWidth(1, 160)
        self.recent.setColumnWidth(4, 128)
        set_empty_text(self.recent, 'Изменений пока нет. Здесь появятся последние заказы.')
        self.recent.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.recent.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.recent.doubleClicked.connect(self._open_from_recent)
        content.addWidget(self.recent, 3, 0, 1, 2)
        content.setColumnStretch(0, 3)
        content.setColumnStretch(1, 1)
        content.setRowStretch(1, 1)
        content.setRowStretch(3, 1)
        self.root.addLayout(content, 1)

    def _open_from_upcoming(self) -> None:
        item = self.upcoming.item(self.upcoming.currentRow(), 0)
        if item:
            self.open_order.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def _open_from_recent(self) -> None:
        item = self.recent.item(self.recent.currentRow(), 0)
        if item:
            self.open_order.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def refresh(self) -> None:
        today = date.today()
        start = datetime.combine(today, time.min)
        end = datetime.combine(today, time.max)
        month_start = datetime(today.year, today.month, 1)
        with self.database.session() as session:
            today_count = session.scalar(select(func.count(Order.id)).where(Order.scheduled_at.between(start, end))) or 0
            in_progress = session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.IN_PROGRESS)) or 0
            ready = session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.READY)) or 0
            month_stats = StatisticsService(session).calculate(month_start.date(), today)
            revenue = month_stats.revenue
            upcoming = list(
                session.scalars(
                    select(Order).options(*OrderRepository.EAGER).where(
                        Order.scheduled_at >= datetime.now(),
                        Order.status.not_in((OrderStatus.CANCELLED, OrderStatus.COMPLETED)),
                    ).order_by(Order.scheduled_at).limit(8)
                ).unique()
            )
            recent = OrderRepository(session).recent(6)
            status_rows = session.execute(select(Order.status, func.count(Order.id)).group_by(Order.status)).all()
        self.today_metric.set_value(str(today_count))
        self.progress_metric.set_value(str(in_progress))
        self.ready_metric.set_value(str(ready))
        self.revenue_metric.set_value(format_money(revenue))
        self.month_note.setText(f"Завершено за месяц: {month_stats.completed} · Выручка рассчитана по завершённым заказам")
        self.month_note.setToolTip('Предварительный показатель. Не является бухгалтерским отчётом.')
        self.upcoming.setRowCount(len(upcoming))
        for row, order in enumerate(upcoming):
            self.upcoming.setItem(row, 0, table_item(format_datetime(order.scheduled_at), order.id))
            self.upcoming.setItem(row, 1, table_item(order.customer.full_name))
            self.upcoming.setItem(row, 2, table_item(f"{order.vehicle.brand} {order.vehicle.model}"))
            self.upcoming.setItem(row, 3, status_item(order.status))
        self.statuses.setRowCount(len(OrderStatus))
        counts = {status: 0 for status in OrderStatus}
        counts.update(dict(status_rows))
        for row, status in enumerate(OrderStatus):
            self.statuses.setItem(row, 0, status_item(status))
            self.statuses.setItem(row, 1, table_item(str(counts[status]), alignment=Qt.AlignmentFlag.AlignCenter))
        self.recent.setRowCount(len(recent))
        for row, order in enumerate(recent):
            self.recent.setItem(row, 0, table_item(order.public_number, order.id))
            self.recent.setItem(row, 1, table_item(format_datetime(order.updated_at)))
            self.recent.setItem(row, 2, table_item(order.customer.full_name))
            self.recent.setItem(row, 3, table_item(f"{order.vehicle.brand} {order.vehicle.model}"))
            self.recent.setItem(row, 4, status_item(order.status))
