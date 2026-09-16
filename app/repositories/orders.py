from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, Order, OrderStatus, Vehicle
from app.services.access_service import require


class OrderRepository:
    EAGER = (
        selectinload(Order.customer),
        selectinload(Order.vehicle),
        selectinload(Order.items),
        selectinload(Order.status_history),
        selectinload(Order.assigned_master),
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    def by_id(self, order_id: int) -> Order | None:
        require(self.session, 'orders')
        return self.session.scalar(select(Order).options(*self.EAGER).where(Order.id == order_id))

    def search(
        self,
        text: str = "",
        status: OrderStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        car_class=None,
    ) -> list[Order]:
        require(self.session, 'orders')
        query = select(Order).join(Order.customer).join(Order.vehicle).options(*self.EAGER)
        if text.strip():
            pattern = f"%{text.strip()}%"
            digits = "".join(ch for ch in text if ch.isdigit())
            query = query.where(
                or_(
                    Order.public_number.ilike(pattern),
                    Customer.full_name.ilike(pattern),
                    Customer.phone.ilike(pattern),
                    Vehicle.brand.ilike(pattern),
                    Vehicle.model.ilike(pattern),
                    Vehicle.license_plate.ilike(pattern),
                    func.phone_digits(Customer.phone).contains(digits) if digits else False,
                )
            )
        if status is not None:
            query = query.where(Order.status == status)
        if date_from is not None:
            query = query.where(Order.scheduled_at >= datetime.combine(date_from, time.min))
        if date_to is not None:
            query = query.where(Order.scheduled_at <= datetime.combine(date_to, time.max))
        if car_class is not None:
            query = query.where(Vehicle.car_class == car_class)
        query = query.order_by(Order.scheduled_at.desc(), Order.id.desc())
        return list(self.session.scalars(query).unique())

    def on_date(self, selected_date: date) -> list[Order]:
        return self.search(date_from=selected_date, date_to=selected_date)[::-1]

    def recent(self, limit: int = 8) -> list[Order]:
        require(self.session, 'orders')
        query = select(Order).options(*self.EAGER).order_by(Order.updated_at.desc()).limit(limit)
        return list(self.session.scalars(query).unique())
