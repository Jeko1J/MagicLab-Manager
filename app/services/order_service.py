from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ALLOWED_STATUS_TRANSITIONS,
    Customer,
    Order,
    OrderItem,
    OrderStatus,
    Service,
    ServicePrice,
    StatusHistory,
    Vehicle,
    User, UserRole,
)
from app.services.calculation_service import CalculationLine, calculate, validate_prepayment
from app.services.access_service import require, AccessDenied
from app.services.audit_service import record

UNCHANGED_MASTER = object()


class OrderValidationError(ValueError):
    pass


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) != 11 or not digits.startswith("7"):
        raise OrderValidationError("Укажите корректный номер телефона")
    return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def validate_customer_fields(full_name: str, phone: str) -> tuple[str, str]:
    if not full_name.strip():
        raise OrderValidationError("Введите имя клиента")
    return full_name.strip(), normalize_phone(phone)


def validate_vehicle_fields(brand: str, model: str, plate: str) -> tuple[str, str, str]:
    if not brand.strip() or not model.strip():
        raise OrderValidationError("Укажите марку и модель автомобиля")
    plate = re.sub(r"\s+", "", plate or "").upper()
    if len(plate) < 5:
        raise OrderValidationError("Укажите государственный номер автомобиля")
    return brand.strip(), model.strip(), plate


class OrderService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _validate_master(self, master_id, existing=None):
        if master_id is None or master_id == existing:
            return master_id
        master = self.session.get(User, master_id, populate_existing=True)
        if not master or not master.is_active or master.role != UserRole.MASTER:
            raise OrderValidationError('Выберите действующую учётную запись мастера')
        return master_id

    def _master_label(self, master_id):
        if master_id is None:
            return 'не назначен'
        master = self.session.get(User, master_id)
        return f'{master.full_name} ({master.username})' if master else f'сотрудник № {master_id}'

    def _next_public_number(self, scheduled_at: datetime) -> str:
        prefix = scheduled_at.strftime("ML-%Y%m-")
        count = self.session.scalar(
            select(func.count(Order.id)).where(Order.public_number.like(f"{prefix}%"))
        ) or 0
        sequence = int(count) + 1
        while self.session.scalar(select(Order.id).where(Order.public_number == f"{prefix}{sequence:04d}")):
            sequence += 1
        return f"{prefix}{sequence:04d}"

    def _lines_for(self, service_ids: list[int], vehicle: Vehicle, existing_items=()):
        if not service_ids:
            raise OrderValidationError("Выберите хотя бы одну услугу")
        unique_ids = list(dict.fromkeys(service_ids))
        snapshots = {item.service_id: item for item in existing_items}
        services = list(
            self.session.scalars(
                select(Service)
                .options(selectinload(Service.prices))
                .where(Service.id.in_(unique_ids), Service.is_active.is_(True))
            ).unique()
        )
        by_id = {service.id: service for service in services}
        if any(service_id not in by_id and service_id not in snapshots for service_id in unique_ids):
            raise OrderValidationError("Одна из выбранных услуг недоступна")
        lines: list[CalculationLine] = []
        for service_id in unique_ids:
            if service_id in snapshots:
                item = snapshots[service_id]
                lines.append(CalculationLine(service_id, item.service_name_snapshot, item.price_snapshot, item.duration_snapshot))
                continue
            service = by_id[service_id]
            price = next((item.price for item in service.prices if item.car_class == vehicle.car_class), None)
            if price is None:
                raise OrderValidationError(f"Для услуги «{service.name}» не указана цена")
            lines.append(CalculationLine(service.id, service.name, price, service.duration_minutes))
        return calculate(lines)

    def create_order(
        self,
        customer: Customer,
        vehicle: Vehicle,
        scheduled_at: datetime,
        service_ids: list[int],
        prepayment=Decimal("0"),
        comment: str = "",
        assigned_master_id: int | None = None,
    ) -> Order:
        require(self.session, 'orders')
        self._validate_master(assigned_master_id)
        if customer.id is None or vehicle.id is None or vehicle.customer_id != customer.id:
            raise OrderValidationError("Выберите автомобиль клиента")
        if not isinstance(scheduled_at, datetime) or not 2000 <= scheduled_at.year <= 2100:
            raise OrderValidationError("Укажите дату и время записи")
        calculation = self._lines_for(service_ids, vehicle)
        payment = validate_prepayment(prepayment, calculation.total_price)
        order = Order(
            public_number=self._next_public_number(scheduled_at),
            customer=customer,
            vehicle=vehicle,
            assigned_master_id=assigned_master_id,
            scheduled_at=scheduled_at.replace(second=0, microsecond=0),
            status=OrderStatus.NEW,
            total_price=calculation.total_price,
            total_duration_minutes=calculation.total_duration_minutes,
            prepayment=payment,
            comment=comment.strip(),
        )
        order.items = [
            OrderItem(
                service_id=line.service_id,
                service_name_snapshot=line.name,
                price_snapshot=line.price,
                duration_snapshot=line.duration_minutes,
            )
            for line in calculation.lines
        ]
        order.status_history.append(
            StatusHistory(old_status=None, new_status=OrderStatus.NEW, comment="Заказ создан")
        )
        self.session.add(order)
        self.session.flush()
        record(self.session, 'Создание заказа', f'Запись на {order.scheduled_at:%d.%m.%Y %H:%M}; мастер: {self._master_label(assigned_master_id)}', order.public_number)
        return order

    def update_order(
        self,
        order: Order,
        scheduled_at: datetime,
        service_ids: list[int],
        prepayment,
        comment: str,
        assigned_master_id=UNCHANGED_MASTER,
    ) -> Order:
        require(self.session, 'orders')
        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED):
            raise OrderValidationError("Завершённый или отменённый заказ нельзя редактировать")
        if not isinstance(scheduled_at, datetime) or not 2000 <= scheduled_at.year <= 2100:
            raise OrderValidationError("Укажите корректную дату и время записи")
        calculation = self._lines_for(service_ids, order.vehicle, order.items)
        payment = validate_prepayment(prepayment, calculation.total_price)
        changes = []
        if order.scheduled_at != scheduled_at.replace(second=0, microsecond=0):
            changes.append(f'Запись: {order.scheduled_at:%d.%m.%Y %H:%M} → {scheduled_at:%d.%m.%Y %H:%M}')
        if set(service_ids) != {item.service_id for item in order.items}:
            changes.append('Изменён перечень услуг и расчёт')
        if order.prepayment != payment:
            changes.append('Изменена предоплата')
        if order.comment != comment.strip():
            changes.append('Изменён комментарий')
        if assigned_master_id is not UNCHANGED_MASTER:
            self._validate_master(assigned_master_id, order.assigned_master_id)
            if order.assigned_master_id != assigned_master_id:
                changes.append(f'Мастер: {self._master_label(order.assigned_master_id)} → {self._master_label(assigned_master_id)}')
                if order.inspection and order.inspection.master_reviewed:
                    order.inspection.master_reviewed = False
                    order.inspection.master_reviewed_by_user_id = None
                    order.inspection.master_reviewed_at = None
                    record(self.session, 'Изменение осмотра', 'Отметка ознакомления мастера сброшена из-за смены назначения', order.public_number)
            order.assigned_master_id = assigned_master_id
        order.scheduled_at = scheduled_at.replace(second=0, microsecond=0)
        order.total_price = calculation.total_price
        order.total_duration_minutes = calculation.total_duration_minutes
        order.prepayment = payment
        order.comment = comment.strip()
        existing = {item.service_id: item for item in order.items}
        order.items[:] = [
            existing[line.service_id] if line.service_id in existing else
            OrderItem(
                service_id=line.service_id,
                service_name_snapshot=line.name,
                price_snapshot=line.price,
                duration_snapshot=line.duration_minutes,
            )
            for line in calculation.lines
        ]
        self.session.flush()
        if changes:
            record(self.session, 'Изменение заказа', '; '.join(changes), order.public_number)
        return order

    def change_status(self, order: Order, new_status: OrderStatus, comment: str = "") -> None:
        actor = require(self.session, 'status')
        if actor.role == UserRole.MASTER:
            with self.session.no_autoflush:
                stored = self.session.connection().execute(select(Order.assigned_master_id, Order.status).where(Order.id == order.id)).first()
            if not stored or stored.assigned_master_id != actor.id:
                raise AccessDenied('Заказ не назначен вам')
            if new_status not in (OrderStatus.IN_PROGRESS, OrderStatus.READY):
                raise AccessDenied('Мастер может выбрать только статусы «В работе» и «Готов»')
            if order.status != stored.status:
                raise OrderValidationError('Статус изменился. Откройте заказ заново')
        old_status = order.status
        if new_status not in ALLOWED_STATUS_TRANSITIONS[old_status]:
            raise OrderValidationError("Недопустимый переход статуса")
        order.status = new_status
        order.status_history.append(
            StatusHistory(old_status=old_status, new_status=new_status, comment=comment.strip())
        )
        self.session.flush()
        from app.models import ORDER_STATUS_LABELS
        record(self.session, 'Изменение статуса', f'{ORDER_STATUS_LABELS[old_status]} → {ORDER_STATUS_LABELS[new_status]}'
               + (f'; {comment.strip()}' if comment.strip() else ''), order.public_number)
