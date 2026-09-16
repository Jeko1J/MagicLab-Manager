from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from decimal import Decimal
from app.models import Service, ServicePrice, CarClass, CAR_CLASS_LABELS
from app.services.access_service import require
from app.services.audit_service import record


class ServiceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def all(self, include_inactive: bool = True) -> list[Service]:
        require(self.session, 'services_view')
        query = select(Service).options(selectinload(Service.prices)).order_by(Service.category, Service.name)
        if not include_inactive:
            query = query.where(Service.is_active.is_(True))
        return list(self.session.scalars(query).unique())

    def by_id(self, service_id: int) -> Service | None:
        require(self.session, 'services_view')
        return self.session.scalar(
            select(Service).options(selectinload(Service.prices)).where(Service.id == service_id)
        )

    def disable(self, service_id: int) -> Service:
        require(self.session, 'services_edit')
        service = self.by_id(service_id)
        if service is None:
            raise ValueError("Услуга не найдена")
        service.is_active = False
        record(self.session, 'Отключение услуги', f'Услуга № {service.id}: {service.name}')
        self.session.flush()
        return service

    def enable(self, service_id: int) -> Service:
        require(self.session, 'services_edit')
        service = self.by_id(service_id)
        if service is None:
            raise ValueError("Услуга не найдена")
        service.is_active = True
        record(self.session, 'Восстановление услуги', f'Услуга № {service.id}: {service.name}')
        self.session.flush()
        return service

    def save(self, service_id, name, category, description, duration, is_active, prices):
        require(self.session, 'services_edit')
        name, category = name.strip(), category.strip()
        if not name or not category:
            raise ValueError('Заполните название и категорию услуги')
        if not isinstance(duration, int) or duration <= 0:
            raise ValueError('Продолжительность должна быть положительной')
        normalized = {}
        for car_class in CarClass:
            price = Decimal(str(prices.get(car_class, '-1')))
            if not price.is_finite() or price < 0:
                raise ValueError('Укажите неотрицательную цену для каждого класса')
            normalized[car_class] = price.quantize(Decimal('.01'))
        duplicate = self.session.scalar(select(Service.id).where(Service.name == name, Service.id != service_id))
        if duplicate:
            raise ValueError('Услуга с таким названием уже существует')
        service = self.by_id(service_id) if service_id else Service()
        if service is None:
            raise ValueError('Услуга не найдена')
        self.session.add(service)
        service.name, service.category, service.description = name, category, description.strip()
        service.duration_minutes, service.is_active = duration, bool(is_active)
        previous = {item.car_class: item for item in service.prices}
        changed_prices = []
        for car_class, price in normalized.items():
            if car_class in previous:
                if previous[car_class].price != price:
                    changed_prices.append(CAR_CLASS_LABELS[car_class])
                previous[car_class].price = price
            else:
                service.prices.append(ServicePrice(car_class=car_class, price=price))
                changed_prices.append(CAR_CLASS_LABELS[car_class])
        self.session.flush()
        record(self.session, 'Изменение услуги' if service_id else 'Создание услуги',
               f'Услуга № {service.id}: {name}; сведения и доступность сохранены' +
               ('; изменены цены: ' + ', '.join(changed_prices) if changed_prices else ''))
        return service
