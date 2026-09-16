from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, OrderStatus, StatusHistory
from app.services.access_service import require


@dataclass(frozen=True)
class StatisticsResult:
    created: int
    completed: int
    cancelled: int
    revenue: Decimal
    average_check: Decimal
    popular_services: tuple[tuple[str, int], ...]
    status_counts: dict[OrderStatus, int]


class StatisticsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def calculate(self, date_from: date, date_to: date) -> StatisticsResult:
        require(self.session, 'statistics')
        start = datetime.combine(date_from, time.min)
        end = datetime.combine(date_to, time.max)
        period = (Order.created_at >= start, Order.created_at <= end)
        created = self.session.scalar(select(func.count(Order.id)).where(*period)) or 0
        def reached(status):
            return Order.id.in_(select(StatusHistory.order_id).where(
                StatusHistory.new_status == status,
                StatusHistory.changed_at >= start, StatusHistory.changed_at <= end,
            ))
        completed = self.session.scalar(
            select(func.count(Order.id)).where(reached(OrderStatus.COMPLETED))
        ) or 0
        cancelled = self.session.scalar(
            select(func.count(Order.id)).where(reached(OrderStatus.CANCELLED))
        ) or 0
        revenue = self.session.scalar(
            select(func.coalesce(func.sum(Order.total_price), 0)).where(
                reached(OrderStatus.COMPLETED)
            )
        )
        revenue = Decimal(str(revenue or 0)).quantize(Decimal("0.00"))
        average = (revenue / completed).quantize(Decimal("0.01")) if completed else Decimal("0.00")
        popular = self.session.execute(
            select(OrderItem.service_name_snapshot, func.count(OrderItem.id).label("quantity"))
            .join(Order)
            .where(*period, Order.status != OrderStatus.CANCELLED)
            .group_by(OrderItem.service_name_snapshot)
            .order_by(func.count(OrderItem.id).desc(), OrderItem.service_name_snapshot)
            .limit(10)
        ).all()
        status_rows = self.session.execute(
            select(Order.status, func.count(Order.id)).where(*period).group_by(Order.status)
        ).all()
        status_counts = {status: 0 for status in OrderStatus}
        status_counts.update(status_rows)
        return StatisticsResult(
            int(created), int(completed), int(cancelled), revenue, average,
            tuple((name, int(quantity)) for name, quantity in popular), status_counts
        )
