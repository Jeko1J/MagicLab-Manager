from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    OWNER = 'OWNER'
    ADMIN = 'ADMIN'
    MASTER = 'MASTER'


USER_ROLE_LABELS = {UserRole.OWNER: 'Руководитель', UserRole.ADMIN: 'Администратор', UserRole.MASTER: 'Мастер-детейлер'}


class CarClass(str, enum.Enum):
    SEDAN = "SEDAN"
    CROSSOVER = "CROSSOVER"
    SUV = "SUV"
    MINIVAN = "MINIVAN"


CAR_CLASS_LABELS = {
    CarClass.SEDAN: "Легковой автомобиль",
    CarClass.CROSSOVER: "Кроссовер",
    CarClass.SUV: "Крупный внедорожник",
    CarClass.MINIVAN: "Минивэн",
}


class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


ORDER_STATUS_LABELS = {
    OrderStatus.NEW: "Новая заявка",
    OrderStatus.BOOKED: "Автомобиль записан",
    OrderStatus.IN_PROGRESS: "Автомобиль в работе",
    OrderStatus.READY: "Автомобиль готов",
    OrderStatus.COMPLETED: "Заказ завершён",
    OrderStatus.CANCELLED: "Заказ отменён",
}


ALLOWED_STATUS_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.BOOKED, OrderStatus.CANCELLED},
    OrderStatus.BOOKED: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.READY},
    OrderStatus.READY: {OrderStatus.COMPLETED, OrderStatus.IN_PROGRESS},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


def enum_type(enum_class: type[enum.Enum]) -> SAEnum:
    return SAEnum(
        enum_class,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    role: Mapped[UserRole] = mapped_column(enum_type(UserRole), default=UserRole.MASTER, server_default='MASTER', nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, server_default='1', nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, nullable=False)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local, nullable=False)

    vehicles: Mapped[list[Vehicle]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", order_by="Vehicle.id"
    )
    orders: Mapped[list[Order]] = relationship(back_populates="customer")


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (Index("ix_vehicles_license_plate", "license_plate"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    license_plate: Mapped[str] = mapped_column(String(20), nullable=False)
    car_class: Mapped[CarClass] = mapped_column(enum_type(CarClass), nullable=False)
    color: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="vehicles")
    orders: Mapped[list[Order]] = relationship(back_populates="vehicle")


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    prices: Mapped[list[ServicePrice]] = relationship(
        back_populates="service", cascade="all, delete-orphan", order_by="ServicePrice.car_class"
    )
    order_items: Mapped[list[OrderItem]] = relationship(back_populates="service")


class ServicePrice(Base):
    __tablename__ = "service_prices"
    __table_args__ = (UniqueConstraint("service_id", "car_class", name="uq_service_car_class"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    car_class: Mapped[CarClass] = mapped_column(enum_type(CarClass), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    service: Mapped[Service] = relationship(back_populates="prices")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_scheduled_at", "scheduled_at"),
        Index("ix_orders_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False)
    assigned_master_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(enum_type(OrderStatus), default=OrderStatus.NEW, nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    prepayment: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local, nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    vehicle: Mapped[Vehicle] = relationship(back_populates="orders")
    assigned_master: Mapped[Optional[User]] = relationship(foreign_keys=[assigned_master_id])
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    status_history: Mapped[list[StatusHistory]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="StatusHistory.changed_at"
    )
    inspection: Mapped[Optional[VehicleInspection]] = relationship(back_populates='order', cascade='all, delete-orphan', uselist=False)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False)
    service_name_snapshot: Mapped[str] = mapped_column(String(180), nullable=False)
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    duration_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
    service: Mapped[Service] = relationship(back_populates="order_items")


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    old_status: Mapped[Optional[OrderStatus]] = mapped_column(enum_type(OrderStatus), nullable=True)
    new_status: Mapped[OrderStatus] = mapped_column(enum_type(OrderStatus), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)

    order: Mapped[Order] = relationship(back_populates="status_history")


class AuditLog(Base):
    __tablename__ = 'audit_log'

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()), unique=True, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True, nullable=False)
    order_number: Mapped[str] = mapped_column(String(30), default='', nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default='', nullable=False)


class VehicleInspection(Base):
    __tablename__ = 'vehicle_inspections'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id', ondelete='CASCADE'), unique=True, nullable=False)
    general_condition: Mapped[str] = mapped_column(String(180), default='', nullable=False)
    general_comment: Mapped[str] = mapped_column(Text, default='', nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local, nullable=False)
    customer_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    customer_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    master_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    master_reviewed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'), nullable=True)
    master_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    order: Mapped[Order] = relationship(back_populates='inspection')
    marks: Mapped[list[DamageMark]] = relationship(back_populates='inspection', cascade='all, delete-orphan', order_by='DamageMark.id')
    photos: Mapped[list[InspectionPhoto]] = relationship(back_populates='inspection', cascade='all, delete-orphan', order_by='InspectionPhoto.id')


class DamageMark(Base):
    __tablename__ = 'damage_marks'
    __table_args__ = (CheckConstraint('normalized_x >= 0 AND normalized_x <= 1'),
                     CheckConstraint('normalized_y >= 0 AND normalized_y <= 1'),
                     CheckConstraint('paint_thickness_um IS NULL OR paint_thickness_um >= 0'))
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey('vehicle_inspections.id', ondelete='CASCADE'), nullable=False, index=True)
    view: Mapped[str] = mapped_column(String(12), nullable=False)
    normalized_x: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_y: Mapped[float] = mapped_column(Float, nullable=False)
    body_element: Mapped[str] = mapped_column(String(32), nullable=False)
    damage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default='', nullable=False)
    paint_thickness_um: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local, nullable=False)
    inspection: Mapped[VehicleInspection] = relationship(back_populates='marks')


class InspectionPhoto(Base):
    __tablename__ = 'inspection_photos'
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey('vehicle_inspections.id', ondelete='CASCADE'), nullable=False, index=True)
    damage_mark_id: Mapped[Optional[int]] = mapped_column(ForeignKey('damage_marks.id', ondelete='CASCADE'), nullable=True)
    file_path: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    caption: Mapped[str] = mapped_column(Text, default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, nullable=False)
    inspection: Mapped[VehicleInspection] = relationship(back_populates='photos')
