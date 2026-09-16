from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.models import CarClass, Customer, OrderStatus, Service, Vehicle
from app.services.order_service import OrderService
from app.services.access_service import require
from app.services.audit_service import record


DEMO_CUSTOMERS = (
    ("Алексей Морозов", "+7 (900) 000-00-01", "Lada", "Vesta", "А247КМ125", CarClass.SEDAN, "Белый"),
    ("Елена Коваль", "+7 (900) 000-00-02", "Kia", "Sportage", "В583ТН125", CarClass.CROSSOVER, "Серый"),
    ("Дмитрий Соколов", "+7 (900) 000-00-03", "Toyota", "Land Cruiser", "Е916РС125", CarClass.SUV, "Чёрный"),
    ("Андрей Лебедев", "+7 (900) 000-00-04", "Volkswagen", "Multivan", "К362АР125", CarClass.MINIVAN, "Синий"),
)


def seed_demo_business_data(database) -> bool:
    """Добавляет явно маркированные учебные записи только в пустую клиентскую базу."""
    with database.session() as session:
        require(session, 'demo')
        if session.scalar(select(Customer.id).limit(1)) is not None:
            return False
        services = list(session.scalars(select(Service).where(Service.is_active.is_(True)).order_by(Service.id)))
        if len(services) < 8:
            return False
        pairs = []
        for full_name, phone, brand, model, plate, car_class, color in DEMO_CUSTOMERS:
            customer = Customer(full_name=full_name, phone=phone, comment="Учебная запись для демонстрации")
            vehicle = Vehicle(
                customer=customer, brand=brand, model=model, license_plate=plate,
                car_class=car_class, color=color, comment="Учебный автомобиль",
            )
            session.add(customer)
            pairs.append((customer, vehicle))
        session.flush()
        today = date.today()
        specs = (
            (0, -3, time(10, 0), (0, 6), OrderStatus.COMPLETED, 'Мойка кузова и обработка стёкол.'),
            (3, -2, time(9, 0), (2, 3), OrderStatus.READY, 'Полировка и защита кузова. Автомобиль ожидает выдачи.'),
            (2, 0, time(8, 0), (1,), OrderStatus.IN_PROGRESS, 'Химчистка салона, особое внимание второму ряду.'),
            (1, 0, time(16, 0), (0, 6), OrderStatus.BOOKED, 'Клиент оставит автомобиль до вечера.'),
            (0, 1, time(11, 0), (5, 7), OrderStatus.NEW, 'Уточнить состояние фар при приёмке.'),
        )
        order_service = OrderService(session)
        for index, (pair_index, day_offset, at_time, service_indexes, target_status, note) in enumerate(specs):
            customer, vehicle = pairs[pair_index]
            scheduled = datetime.combine(today + timedelta(days=day_offset), at_time)
            order = order_service.create_order(
                customer, vehicle, scheduled,
                [services[value].id for value in service_indexes],
                0, f"Учебные данные. {note}",
            )
            path = {
                OrderStatus.NEW: (),
                OrderStatus.BOOKED: (OrderStatus.BOOKED,),
                OrderStatus.IN_PROGRESS: (OrderStatus.BOOKED, OrderStatus.IN_PROGRESS),
                OrderStatus.READY: (OrderStatus.BOOKED, OrderStatus.IN_PROGRESS, OrderStatus.READY),
                OrderStatus.COMPLETED: (OrderStatus.BOOKED, OrderStatus.IN_PROGRESS, OrderStatus.READY, OrderStatus.COMPLETED),
            }[target_status]
            for status in path:
                note = {OrderStatus.BOOKED: 'Запись подтверждена', OrderStatus.IN_PROGRESS: 'Автомобиль принят',
                        OrderStatus.READY: 'Работы выполнены', OrderStatus.COMPLETED: 'Автомобиль выдан'}[status]
                order_service.change_status(order, status, note)
            # Учебная хронология: завершённые работы не записаны на будущую дату.
            created = min(scheduled - timedelta(days=2), datetime.now() - timedelta(hours=3))
            order.created_at = created
            session.flush()
            for history_index, history in enumerate(order.status_history):
                if history_index <= 1:
                    history.changed_at = created + timedelta(minutes=30 * history_index)
                elif history.new_status == OrderStatus.IN_PROGRESS:
                    history.changed_at = scheduled
                else:
                    finished = scheduled + timedelta(minutes=order.total_duration_minutes)
                    if finished.hour < 9:
                        finished = finished.replace(hour=10, minute=0)
                    elif finished.hour >= 19:
                        finished = (finished + timedelta(days=1)).replace(hour=10, minute=0)
                    history.changed_at = finished + timedelta(minutes=30 if history.new_status == OrderStatus.COMPLETED else 0)
            order.updated_at = max(history.changed_at for history in order.status_history)
        record(session, 'Учебные данные', 'Добавлены учебные клиенты, автомобили и заказы в пустую базу')
        session.commit()
        return True
