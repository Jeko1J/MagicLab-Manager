"""Мастер получает только рабочую проекцию своих заказов, без финансов и клиентов."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import Order, OrderItem, OrderStatus, Vehicle
from app.services.access_service import require, AccessDenied
from app.services.order_service import OrderService


@dataclass(frozen=True)
class MasterOrder:
    id: int
    public_number: str
    scheduled_at: datetime
    expected_finish: datetime
    status: OrderStatus
    vehicle: str
    license_plate: str
    color: str
    comment: str
    total_duration_minutes: int
    services: tuple[tuple[str, int], ...]


class MasterOrderService:
    def __init__(self, session):
        self.session = session

    def list_orders(self, text='', current_only=True, order_id=None):
        actor = require(self.session, 'master_orders')
        query = select(Order.id, Order.public_number, Order.scheduled_at, Order.status, Order.comment,
                       Order.total_duration_minutes, Vehicle.brand, Vehicle.model, Vehicle.license_plate, Vehicle.color
                       ).join(Vehicle, Order.vehicle_id == Vehicle.id).where(Order.assigned_master_id == actor.id)
        if order_id is not None:
            query = query.where(Order.id == order_id)
        if current_only:
            query = query.where(Order.status.notin_((OrderStatus.COMPLETED, OrderStatus.CANCELLED)))
        if text.strip():
            pattern = '%' + text.strip() + '%'
            query = query.where(Order.public_number.ilike(pattern) | Vehicle.brand.ilike(pattern)
                                | Vehicle.model.ilike(pattern) | Vehicle.license_plate.ilike(pattern))
        rows = self.session.execute(query.order_by(Order.scheduled_at, Order.id)).all()
        ids = [row.id for row in rows]
        items = self.session.execute(select(OrderItem.order_id, OrderItem.service_name_snapshot, OrderItem.duration_snapshot)
                                     .where(OrderItem.order_id.in_(ids)).order_by(OrderItem.id)).all() if ids else []
        grouped = {}
        for item in items:
            grouped.setdefault(item.order_id, []).append((item.service_name_snapshot, item.duration_snapshot))
        return [MasterOrder(row.id, row.public_number, row.scheduled_at,
                            row.scheduled_at + timedelta(minutes=row.total_duration_minutes), row.status,
                            f'{row.brand} {row.model}', row.license_plate, row.color, row.comment,
                            row.total_duration_minutes, tuple(grouped.get(row.id, ()))) for row in rows]

    def by_id(self, order_id):
        rows = self.list_orders(current_only=False, order_id=order_id)
        if not rows:
            raise AccessDenied('Заказ не найден или не назначен вам')
        return rows[0]

    def change_status(self, order_id, status, comment=''):
        self.by_id(order_id)
        order = self.session.get(Order, order_id)
        OrderService(self.session).change_status(order, status, comment)
