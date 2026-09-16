"""Отдельная воспроизводимая учебная база для отчёта. Существующие данные не дополняет."""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import select
from app.database import Database
from app.models import CarClass, Customer, Order, OrderStatus, Service, UserRole, Vehicle
from app.repositories.customers import CustomerRepository
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.services.order_service import OrderService
from app.services.audit_service import record

DEMO_PASSWORD = 'Demo-2026!'
CUSTOMERS = (
    ('Алексей Морозов', 'Lada', 'Vesta', 'А247КМ125', CarClass.SEDAN, 'Белый'),
    ('Елена Коваль', 'Kia', 'Sportage', 'В583ТН125', CarClass.CROSSOVER, 'Серый'),
    ('Дмитрий Соколов', 'Toyota', 'Land Cruiser', 'Е916РС125', CarClass.SUV, 'Чёрный'),
    ('Андрей Лебедев', 'Volkswagen', 'Multivan', 'К362АР125', CarClass.MINIVAN, 'Синий'),
    ('Ольга Белова', 'Toyota', 'Camry', 'М408ЕА125', CarClass.SEDAN, 'Серебристый'),
    ('Роман Орлов', 'Hyundai', 'Tucson', 'Н715ВК125', CarClass.CROSSOVER, 'Белый'),
    ('Ирина Фролова', 'Skoda', 'Octavia', 'О632ТМ125', CarClass.SEDAN, 'Красный'),
    ('Павел Волков', 'Mitsubishi', 'Pajero', 'Р259АН125', CarClass.SUV, 'Серый'),
)


def seed_report_data(database, anchor: date):
    with database.session() as session:
        if session.scalar(select(Customer.id)) or AuthService(session).has_users():
            raise ValueError('Нужна пустая отдельная учебная база')
        owner = AuthService(session).create_admin('demo-owner', DEMO_PASSWORD, 'Руководитель · учебный аккаунт')
        session.commit()
        database.sign_in(owner)
    database.seed_demo_services()
    with database.session() as session:
        users = UserService(session)
        admin = users.create('demo-admin', DEMO_PASSWORD, 'Администратор · учебный аккаунт', UserRole.ADMIN)
        master = users.create('demo-master', DEMO_PASSWORD, 'Сергей · учебный мастер', UserRole.MASTER)
        novice = users.create('demo-novice', DEMO_PASSWORD, 'Елена · учебный мастер', UserRole.MASTER)
        repo = CustomerRepository(session)
        pairs = []
        for index, (name, brand, model, plate, car_class, color) in enumerate(CUSTOMERS, 1):
            customer = repo.create(name, f'+790000000{index:02}', 'Учебные данные. Совпадения случайны. Не использовать для связи.')
            vehicle = repo.add_vehicle(customer, brand, model, plate, car_class, color, 'Учебный автомобиль')
            pairs.append((customer, vehicle))
        services = {item.name: item.id for item in session.scalars(select(Service))}
        wash, rain, cabin, polish, ceramic = 'Детейлинг-мойка', 'Антидождь', 'Химчистка салона', 'Полировка кузова', 'Керамическое покрытие'
        headlights, ozone, leather, film = 'Полировка фар', 'Озонация салона', 'Защитное покрытие кожи', 'Защитная полиуретановая плёнка'
        # Клиент, смещение дня, час, статус, услуги, мастер. Все события синтетические.
        specs = (
            (0, -8, 10, 'COMPLETED', (wash, rain), master),
            (1, -6, 9, 'COMPLETED', (polish, ceramic), master),
            (2, -4, 8, 'COMPLETED', (cabin,), novice),
            (3, -3, 9, 'COMPLETED', (wash, leather), novice),
            (4, -4, 14, 'CANCELLED', (wash,), None),
            (5, -2, 10, 'READY', (wash, headlights), master),
            (6, -1, 9, 'READY', (wash, rain), novice),
            (2, 0, 8, 'IN_PROGRESS', (cabin,), master),
            (7, 0, 9, 'IN_PROGRESS', (film,), novice),
            (1, 0, 16, 'BOOKED', (wash, rain), master),
            (4, 0, 17, 'BOOKED', (headlights,), novice),
            (6, 0, 18, 'BOOKED', (wash,), master),
            (0, 1, 10, 'NEW', (headlights, ozone), None),
            (5, 1, 13, 'BOOKED', (wash, rain), novice),
            (3, 2, 9, 'NEW', (cabin, leather), None),
            (7, 2, 11, 'BOOKED', (polish, ceramic), master),
            (4, 3, 10, 'NEW', (wash, rain), None),
            (6, 3, 14, 'CANCELLED', (cabin,), None),
        )
        paths = {
            'NEW': (), 'BOOKED': ('BOOKED',), 'IN_PROGRESS': ('BOOKED', 'IN_PROGRESS'),
            'READY': ('BOOKED', 'IN_PROGRESS', 'READY'),
            'COMPLETED': ('BOOKED', 'IN_PROGRESS', 'READY', 'COMPLETED'), 'CANCELLED': ('CANCELLED',),
        }
        order_service = OrderService(session)
        created_orders = []
        for index, (customer_index, offset, hour, status, names, assigned) in enumerate(specs, 1):
            customer, vehicle = pairs[customer_index]
            scheduled = datetime.combine(anchor + timedelta(days=offset), time(hour))
            order = order_service.create_order(customer, vehicle, scheduled, [services[name] for name in names],
                1000 if status not in ('NEW', 'CANCELLED') else 0,
                'Учебные данные для отчёта. ' + ('Проверить состояние стёкол перед нанесением покрытия.' if rain in names else 'Уточнить состояние автомобиля при приёмке.'),
                assigned_master_id=assigned.id if assigned else None)
            for step in paths[status]:
                order_service.change_status(order, OrderStatus(step), 'Учебная история для демонстрации')
            # Даты истории моделируют жизненный цикл. Журнал действий сохраняет реальное время генерации.
            created = min(scheduled - timedelta(days=2), datetime.combine(anchor, time(6)))
            order.created_at = created
            finished = scheduled + timedelta(minutes=order.total_duration_minutes)
            session.flush()
            for history in order.status_history:
                history.changed_at = {
                    OrderStatus.NEW: created, OrderStatus.BOOKED: created + timedelta(minutes=20),
                    OrderStatus.IN_PROGRESS: scheduled, OrderStatus.READY: finished,
                    OrderStatus.COMPLETED: finished + timedelta(minutes=30),
                    OrderStatus.CANCELLED: created + timedelta(minutes=40),
                }[history.new_status]
            order.updated_at = max(item.changed_at for item in order.status_history)
            created_orders.append({'index': index, 'id': order.id, 'number': order.public_number, 'status': status,
                'customer': customer.full_name, 'vehicle': f'{vehicle.brand} {vehicle.model}', 'plate': vehicle.license_plate,
                'scheduled_at': scheduled.isoformat(), 'total_price': str(order.total_price),
                'prepayment': str(order.prepayment), 'duration_minutes': order.total_duration_minutes,
                'master': assigned.username if assigned else None})
        record(session, 'Подготовка отчёта', 'Созданы 18 синтетических заказов, 8 клиентов, 8 автомобилей. Это не реальные обращения.')
        session.commit()
    return {'application': 'MagicLab Manager', 'synthetic': True, 'anchor_date': anchor.isoformat(),
        'generated_at': datetime.now().isoformat(), 'orders': created_orders,
        'counts': {'customers': 8, 'vehicles': 8, 'services': 10, 'prices': 40, 'users': 4, 'orders': len(created_orders),
                   'statuses': dict(Counter(item['status'] for item in created_orders))},
        'sample_order_id': created_orders[9]['id'], 'sample_order_number': created_orders[9]['number'],
        'sample_customer_id': pairs[1][0].id, 'sample_vehicle_id': pairs[1][1].id,
        'owner_id': owner.id, 'admin_id': admin.id, 'master_id': master.id}


def create_demo(output: Path, anchor: date):
    output = output.resolve()
    db_path = output / 'data/magiclab.db'
    if db_path.exists():
        raise ValueError('Учебная база уже существует. Выберите новую папку; данные не перезаписываются.')
    for name in ('data', 'backups', 'exports'):
        (output / name).mkdir(parents=True, exist_ok=True)
    database = Database(f'sqlite:///{db_path.as_posix()}')
    try:
        database.create_schema()
        manifest = seed_report_data(database, anchor)
    finally:
        database.dispose()
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/demo')
    parser.add_argument('--date', type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    print(json.dumps(create_demo(args.output, args.date)['counts'], ensure_ascii=False))
