from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer, Order, OrderStatus, Vehicle
from app.services.order_service import validate_customer_fields, validate_vehicle_fields
from app.services.access_service import require
from app.services.audit_service import record


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_id(self, customer_id: int) -> Customer | None:
        require(self.session, 'customers')
        return self.session.scalar(
            select(Customer).options(selectinload(Customer.vehicles), selectinload(Customer.orders)).where(Customer.id == customer_id)
        )

    def by_phone(self, phone: str) -> Customer | None:
        require(self.session, 'customers')
        return self.session.scalar(select(Customer).where(Customer.phone == phone))

    def search(self, text: str = "") -> list[Customer]:
        require(self.session, 'customers')
        query = select(Customer).options(selectinload(Customer.vehicles)).order_by(Customer.full_name)
        if text.strip():
            pattern = f"%{text.strip()}%"
            digits = "".join(ch for ch in text if ch.isdigit())
            conditions = [Customer.full_name.ilike(pattern), Customer.phone.ilike(pattern)]
            if digits:
                conditions.append(func.phone_digits(Customer.phone).contains(digits))
            query = query.where(or_(*conditions))
        return list(self.session.scalars(query).unique())

    def completed_total(self, customer_id: int):
        require(self.session, 'customers')
        return self.session.scalar(
            select(func.coalesce(func.sum(Order.total_price), 0)).where(
                Order.customer_id == customer_id, Order.status == OrderStatus.COMPLETED
            )
        )

    def create(self, full_name: str, phone: str, comment: str = "") -> Customer:
        require(self.session, 'customers')
        full_name, phone = validate_customer_fields(full_name, phone)
        if self.by_phone(phone) is not None:
            raise ValueError("Клиент с таким телефоном уже существует")
        customer = Customer(full_name=full_name, phone=phone, comment=comment.strip())
        self.session.add(customer)
        self.session.flush()
        record(self.session, 'Создание клиента', f'Создан клиент № {customer.id}')
        return customer

    def update(self, customer_id, full_name, phone, comment=''):
        require(self.session, 'customers')
        full_name, phone = validate_customer_fields(full_name, phone)
        customer = self.by_id(customer_id)
        if customer is None:
            raise ValueError('Клиент не найден')
        duplicate = self.by_phone(phone)
        if duplicate and duplicate.id != customer_id:
            raise ValueError('Клиент с таким телефоном уже существует')
        changed = [label for label, old, new in (
            ('имя', customer.full_name, full_name), ('телефон', customer.phone, phone),
            ('комментарий', customer.comment, comment.strip())) if old != new]
        customer.full_name, customer.phone, customer.comment = full_name, phone, comment.strip()
        if changed:
            record(self.session, 'Изменение клиента', f'Клиент № {customer.id}: ' + ', '.join(changed))
        self.session.flush()
        return customer

    def add_vehicle(
        self,
        customer: Customer,
        brand: str,
        model: str,
        license_plate: str,
        car_class,
        color: str = "",
        comment: str = "",
    ) -> Vehicle:
        require(self.session, 'customers')
        brand, model, license_plate = validate_vehicle_fields(brand, model, license_plate)
        vehicle = Vehicle(
            customer=customer,
            brand=brand.strip(),
            model=model.strip(),
            license_plate=license_plate.strip().upper(),
            car_class=car_class,
            color=color.strip(),
            comment=comment.strip(),
        )
        self.session.add(vehicle)
        self.session.flush()
        record(self.session, 'Создание автомобиля', f'Автомобиль № {vehicle.id}: {vehicle.license_plate}')
        return vehicle

    def update_vehicle(self, vehicle_id, brand, model, license_plate, car_class, color='', comment=''):
        require(self.session, 'customers')
        vehicle = self.session.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise ValueError('Автомобиль не найден')
        brand, model, license_plate = validate_vehicle_fields(brand, model, license_plate)
        values = {'brand': brand, 'model': model, 'license_plate': license_plate,
                  'car_class': car_class, 'color': color.strip(), 'comment': comment.strip()}
        labels = {'brand': 'марка', 'model': 'модель', 'license_plate': 'госномер',
                  'car_class': 'класс', 'color': 'цвет', 'comment': 'комментарий'}
        changed = [labels[key] for key, value in values.items() if getattr(vehicle, key) != value]
        for key, value in values.items():
            setattr(vehicle, key, value)
        if changed:
            record(self.session, 'Изменение автомобиля', f'Автомобиль № {vehicle.id}: ' + ', '.join(changed))
        self.session.flush()
        return vehicle
