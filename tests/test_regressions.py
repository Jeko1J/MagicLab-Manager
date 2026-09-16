from datetime import date, datetime, timedelta
from decimal import Decimal
import sqlite3

import pytest

from app.database import Database
from app.models import OrderStatus
from app.repositories.customers import CustomerRepository
from app.repositories.orders import OrderRepository
from app.services.backup_service import BackupError, create_backup, restore_backup, verify_sqlite
from app.services.calculation_service import CalculationError, money
from app.services.order_service import OrderService
from app.services.statistics_service import StatisticsService
from app.services.auth_service import AuthService


def test_edit_preserves_disabled_service_snapshots(session, catalog):
    service = OrderService(session)
    order = service.create_order(catalog['customer'], catalog['sedan'], datetime.now(), [catalog['wash'].id])
    session.commit()
    catalog['wash'].name = 'Новое название'
    catalog['wash'].duration_minutes = 999
    catalog['wash'].is_active = False
    for price in catalog['wash'].prices:
        price.price = 9999
    session.commit()
    service.update_order(order, datetime.now(), [catalog['wash'].id], 200, 'Уточнение')
    session.commit()
    assert order.total_price == Decimal('1000')
    assert order.items[0].service_name_snapshot == 'Мойка'
    assert order.items[0].duration_snapshot == 60


def test_cyrillic_and_unformatted_phone_search(session, catalog):
    order = OrderService(session).create_order(catalog['customer'], catalog['sedan'], datetime.now(), [catalog['wash'].id])
    session.commit()
    assert OrderRepository(session).search('иван')[0].id == order.id
    assert OrderRepository(session).search('а123вс')[0].id == order.id
    assert OrderRepository(session).search('9991234567')[0].id == order.id
    assert CustomerRepository(session).search('999123')[0].id == catalog['customer'].id


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity'])
def test_nonfinite_money_rejected(value):
    with pytest.raises(CalculationError):
        money(value)


def test_completion_statistics_use_completion_date(session, catalog):
    service = OrderService(session)
    order = service.create_order(catalog['customer'], catalog['sedan'], datetime.now(), [catalog['wash'].id])
    order.created_at = datetime.now() - timedelta(days=45)
    for status in (OrderStatus.BOOKED, OrderStatus.IN_PROGRESS, OrderStatus.READY, OrderStatus.COMPLETED):
        service.change_status(order, status)
    session.commit()
    result = StatisticsService(session).calculate(date.today(), date.today())
    assert result.created == 0
    assert result.completed == 1
    assert result.revenue == Decimal('1000')


def test_backup_rejects_partial_database(tmp_path):
    path = tmp_path / 'incomplete.db'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE orders (id INTEGER)')
    with pytest.raises(BackupError):
        verify_sqlite(path)


def test_restore_creates_safety_copy(tmp_path):
    current = tmp_path / 'current.db'
    db = Database(f'sqlite:///{current.as_posix()}')
    db.create_schema()
    db.seed_demo_services()
    with db.session() as session:
        user = AuthService(session).create_admin('owner', 'test-password', 'Руководитель')
        session.commit()
        db.sign_in(user)
    with db.session() as session:
        original = create_backup(current, tmp_path / 'copies', session=session)
        session.commit()
    with db.session() as session:
        restored, safety = restore_backup(current, original, tmp_path / 'copies', session=session)
    assert restored == current
    assert safety.exists() and safety.name.startswith('before_restore_')
    verify_sqlite(current)
