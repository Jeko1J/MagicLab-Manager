from datetime import date, datetime
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import select, event

from app.database import Database
from app.models import AuditLog, Customer, Order, OrderStatus, User, UserRole
from app.repositories.customers import CustomerRepository
from app.repositories.orders import OrderRepository
from app.repositories.services import ServiceRepository
from app.services.access_service import AccessDenied, require
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService, verify_password
from app.services.backup_service import create_backup, restore_backup, verify_sqlite, BackupError
from app.services.calendar_export_service import CalendarExportService
from app.services.master_order_service import MasterOrderService
from app.services.order_service import OrderService
from app.services.statistics_service import StatisticsService
from app.services.user_service import UserService


@pytest.fixture
def employees(database):
    with database.session() as session:
        owner = session.get(User, database.actor_id)
        service = UserService(session)
        admin = service.create('admin', 'admin-password', 'Администратор', UserRole.ADMIN)
        master = service.create('master', 'master-password', 'Опытный мастер', UserRole.MASTER)
        novice = service.create('novice', 'novice-password', 'Новый мастер', UserRole.MASTER)
        session.commit()
    return {UserRole.OWNER: owner, UserRole.ADMIN: admin, UserRole.MASTER: master, 'novice': novice}


@pytest.fixture
def assigned_orders(database, catalog, employees):
    with database.session() as session:
        from app.models import Vehicle
        service = OrderService(session)
        orders = []
        for master_id in (employees[UserRole.MASTER].id, employees['novice'].id, None):
            order = service.create_order(session.get(Customer, catalog['customer'].id), session.get(Vehicle, catalog['sedan'].id),
                datetime(2026, 9, 4, 10), [catalog['wash'].id], 100, 'Рабочий комментарий', assigned_master_id=master_id)
            service.change_status(order, OrderStatus.BOOKED)
            orders.append(order.id)
        session.commit()
    return orders


@pytest.mark.parametrize('role', list(UserRole))
@pytest.mark.parametrize('permission,allowed', [
    ('orders', {'OWNER', 'ADMIN'}), ('customers', {'OWNER', 'ADMIN'}),
    ('services_view', {'OWNER', 'ADMIN'}), ('services_edit', {'OWNER'}),
    ('statistics', {'OWNER'}), ('users', {'OWNER'}), ('audit', {'OWNER'}),
    ('backup', {'OWNER'}), ('restore', {'OWNER'}), ('bulk_export', {'OWNER'}),
    ('calendar_export', {'OWNER', 'ADMIN'}), ('documents', {'OWNER', 'ADMIN'}),
    ('master_orders', {'MASTER'}), ('account', {'OWNER', 'ADMIN', 'MASTER'}),
])
def test_permission_matrix(database, employees, role, permission, allowed):
    database.sign_in(employees[role])
    with database.session() as session:
        if role.value in allowed:
            assert require(session, permission).id == employees[role].id
        else:
            with pytest.raises(AccessDenied):
                require(session, permission)


@pytest.mark.parametrize('role', [UserRole.ADMIN, UserRole.MASTER])
def test_sensitive_services_reject_non_owner(database, employees, catalog, role, tmp_path):
    database.sign_in(employees[role])
    with database.session() as session:
        attempts = (
            lambda: StatisticsService(session).calculate(date.today(), date.today()),
            lambda: UserService(session).list_users(),
            lambda: UserService(session).create('unauthorized', 'password', 'Запрещённый', UserRole.OWNER),
            lambda: UserService(session).reset_password(employees[UserRole.OWNER].id, 'changed'),
            lambda: ServiceRepository(session).disable(catalog['wash'].id),
            lambda: AuditService(session).search(),
            lambda: create_backup(tmp_path / 'not-existing.db', tmp_path / 'copies', session=session),
            lambda: restore_backup(tmp_path / 'current.db', tmp_path / 'copy.db', tmp_path / 'copies', session=session),
        )
        for attempt in attempts:
            with pytest.raises(AccessDenied):
                attempt()
    assert not (tmp_path / 'copies').exists()


def test_master_projection_scoped_and_has_no_financial_fields(database, employees, assigned_orders):
    database.sign_in(employees[UserRole.MASTER])
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())
    event.listen(database.engine, 'before_cursor_execute', capture)
    try:
        with database.session() as session:
            rows = MasterOrderService(session).list_orders()
            assert [row.id for row in rows] == assigned_orders[:1]
            assert rows[0].services == (('Мойка', 60),)
            assert rows[0].expected_finish == datetime(2026, 9, 4, 11)
            assert not hasattr(rows[0], 'total_price') and not hasattr(rows[0], 'customer')
            with pytest.raises(AccessDenied):
                MasterOrderService(session).by_id(assigned_orders[1])
            with pytest.raises(AccessDenied):
                MasterOrderService(session).by_id(assigned_orders[2])
    finally:
        event.remove(database.engine, 'before_cursor_execute', capture)
    assert not any('price' in sql or 'prepayment' in sql or 'password_hash' in sql or 'customers' in sql for sql in statements)


def test_master_cannot_use_full_order_customer_or_catalog_apis(database, employees, assigned_orders, catalog):
    database.sign_in(employees[UserRole.MASTER])
    with database.session() as session:
        for operation in (
            lambda: OrderRepository(session).by_id(assigned_orders[0]),
            lambda: OrderRepository(session).search(),
            lambda: CustomerRepository(session).search(),
            lambda: CustomerRepository(session).create('Новый', '+79991230000'),
            lambda: CustomerRepository(session).update(catalog['customer'].id, 'Изменённый', '+79991230000'),
            lambda: ServiceRepository(session).all(),
            lambda: CalendarExportService(session).prepare(date.today(), date.today(), 'UTC'),
            lambda: OrderService(session).update_order(session.get(Order, assigned_orders[0]), datetime.now(), [], 0, 'Изменено'),
        ):
            with pytest.raises(AccessDenied):
                operation()


def test_master_status_changes_and_audit(database, employees, assigned_orders):
    master = employees[UserRole.MASTER]
    database.sign_in(master)
    with database.session() as session:
        service = MasterOrderService(session)
        for status in (OrderStatus.IN_PROGRESS, OrderStatus.READY, OrderStatus.IN_PROGRESS):
            service.change_status(assigned_orders[0], status, 'Проверено мастером')
        for status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.BOOKED):
            with pytest.raises(AccessDenied):
                service.change_status(assigned_orders[0], status)
        with pytest.raises(AccessDenied):
            service.change_status(assigned_orders[1], OrderStatus.IN_PROGRESS)
        session.commit()
    database.sign_in(employees[UserRole.OWNER])
    with database.session() as session:
        logs = list(session.scalars(select(AuditLog).where(AuditLog.user_id == master.id, AuditLog.action == 'Изменение статуса')))
        assert len(logs) == 3
        assert all(entry.username == 'master' and entry.order_number and entry.occurred_at for entry in logs)
        order = OrderRepository(session).by_id(assigned_orders[0])
        assert len(order.status_history) == 5


def test_admin_can_manage_operational_records_and_assign_master(database, employees, catalog):
    database.sign_in(employees[UserRole.ADMIN])
    with database.session() as session:
        from app.models import CarClass
        customers = CustomerRepository(session)
        customer = customers.create('Клиент', '+79001112233')
        vehicle = customers.add_vehicle(customer, 'Kia', 'Rio', 'А001АА125', CarClass.SEDAN)
        customers.update(customer.id, 'Клиент изменён', '+79001112233', 'Примечание')
        customers.update_vehicle(vehicle.id, 'Kia', 'Rio', 'А002АА125', CarClass.SEDAN, 'Белый')
        order = OrderService(session).create_order(customer, vehicle, datetime.now(), [catalog['wash'].id],
            assigned_master_id=employees[UserRole.MASTER].id)
        assert order.assigned_master_id == employees[UserRole.MASTER].id
        OrderService(session).update_order(order, datetime.now(), [catalog['wash'].id], 0, 'Работы', assigned_master_id=employees['novice'].id)
        assert order.assigned_master_id == employees['novice'].id
        assert ServiceRepository(session).all()
        session.commit()
        actions = set(session.scalars(select(AuditLog.action)))
        assert {'Создание клиента', 'Изменение клиента', 'Создание автомобиля', 'Изменение автомобиля', 'Создание заказа', 'Изменение заказа'} <= actions


def test_reassignment_removes_master_access(database, employees, assigned_orders, catalog):
    with database.session() as session:
        order = OrderRepository(session).by_id(assigned_orders[0])
        OrderService(session).update_order(order, order.scheduled_at, [catalog['wash'].id], order.prepayment, order.comment,
                                          assigned_master_id=employees['novice'].id)
        session.commit()
    database.sign_in(employees[UserRole.MASTER])
    with database.session() as session:
        with pytest.raises(AccessDenied):
            MasterOrderService(session).by_id(assigned_orders[0])


def test_user_management_reset_block_and_no_passwords_in_audit(database, employees):
    with database.session() as session:
        service = UserService(session)
        master = employees[UserRole.MASTER]
        service.update(master.id, 'master-renamed', 'Мастер после изменения', UserRole.MASTER, True)
        service.reset_password(master.id, 'private-reset-password')
        session.commit()
        assert AuthService(session).authenticate('master-renamed', 'master-password') is None
        assert AuthService(session).authenticate('master-renamed', 'private-reset-password').id == master.id
        service.update(master.id, 'master-renamed', 'Мастер', UserRole.MASTER, False)
        session.commit()
        assert AuthService(session).authenticate('master-renamed', 'private-reset-password') is None
        service.update(master.id, 'master-renamed', 'Мастер', UserRole.MASTER, True)
        session.commit()
        assert AuthService(session).authenticate('master-renamed', 'private-reset-password')
        text = '\n'.join(entry.description for entry in session.scalars(select(AuditLog)))
        assert 'private-reset-password' not in text and 'pbkdf2_sha256' not in text


def test_duplicate_logins_and_self_lockout_prevented(database, employees):
    with database.session() as session:
        users = UserService(session)
        with pytest.raises(ValueError, match='занято'):
            users.create('MASTER', 'password', 'Дубликат', UserRole.MASTER)
        owner = employees[UserRole.OWNER]
        for role, active in ((UserRole.OWNER, False), (UserRole.ADMIN, True)):
            with pytest.raises(ValueError):
                users.update(owner.id, owner.username, owner.full_name, role, active)
        with pytest.raises(AccessDenied):
            AuthService(session).create_admin('backdoor', 'password', 'Повторный первый вход')


def test_log_survives_user_rename_and_transaction_rollback(database, employees):
    with database.session() as session:
        customer = CustomerRepository(session).create('Отмена транзакции', '+79001119999')
        session.rollback()
        assert session.scalar(select(Customer.id).where(Customer.phone == '+7 (900) 111-99-99')) is None
        assert session.scalar(select(AuditLog.id).where(AuditLog.description.like(f'Создан клиент № {customer.id}'))) is None


def test_logout_invalidates_existing_sessions(database, employees):
    session = database.session()
    assert require(session, 'users')
    database.sign_out()
    with pytest.raises(AccessDenied):
        UserService(session).list_users()
    session.close()


@pytest.mark.parametrize('field,value', [('is_active', False), ('auth_version', 2), ('role', UserRole.MASTER)])
def test_live_access_ignores_cached_user_role(database, employees, field, value):
    user = employees[UserRole.ADMIN]
    database.sign_in(user)
    with database.session() as session:
        assert require(session, 'orders')
        session.connection().execute(User.__table__.update().where(User.id == user.id).values({field: value}))
        session.commit()
        with pytest.raises(AccessDenied):
            OrderRepository(session).search()


def test_anonymous_services_fail_closed(anonymous_database, tmp_path):
    with anonymous_database.session() as session:
        for operation in (lambda: CustomerRepository(session).search(), lambda: OrderRepository(session).search(),
                          lambda: UserService(session).list_users(), lambda: MasterOrderService(session).list_orders()):
            with pytest.raises(AccessDenied):
                operation()
    with pytest.raises(AccessDenied):
        create_backup(tmp_path / 'anything.db', tmp_path)


def test_direct_status_api_cannot_change_other_masters_order(database, employees, assigned_orders):
    database.sign_in(employees[UserRole.MASTER])
    with database.session() as session:
        for order_id in assigned_orders[1:]:
            with pytest.raises(AccessDenied, match='не назначен'):
                OrderService(session).change_status(session.get(Order, order_id), OrderStatus.IN_PROGRESS)
        session.commit()
        assert all(session.get(Order, order_id).status == OrderStatus.BOOKED for order_id in assigned_orders)


@pytest.mark.parametrize('target', ['owner', 'admin', 'blocked', 'missing'])
def test_invalid_master_assignment_rejected(database, employees, catalog, target):
    from app.models import Vehicle
    with database.session() as session:
        master = session.get(User, employees[UserRole.MASTER].id)
        master.is_active = False
        session.commit()
        master_id = {'owner': employees[UserRole.OWNER].id, 'admin': employees[UserRole.ADMIN].id,
                     'blocked': master.id, 'missing': 99999}[target]
        with pytest.raises(ValueError, match='учётную запись мастера'):
            OrderService(session).create_order(session.get(Customer, catalog['customer'].id),
                session.get(Vehicle, catalog['sedan'].id), datetime.now(), [catalog['wash'].id], assigned_master_id=master_id)
        assert session.scalar(select(Order.id)) is None


def test_only_owner_can_save_prices(database, employees):
    from app.models import CarClass
    prices = {car_class: 1234 for car_class in CarClass}
    with database.session() as session:
        service = ServiceRepository(session).save(None, 'Тестовая услуга', 'Тест', 'Описание', 30, True, prices)
        session.commit()
        service_id = service.id
        assert all(item.price == 1234 for item in service.prices)
    database.sign_in(employees[UserRole.ADMIN])
    with database.session() as session:
        with pytest.raises(AccessDenied):
            ServiceRepository(session).save(service_id, 'Подмена', 'Тест', '', 30, True, prices)
        assert ServiceRepository(session).by_id(service_id).name == 'Тестовая услуга'


def test_data_root_override_keeps_bundled_resources(monkeypatch, tmp_path):
    import importlib
    from app import config
    original = config.RESOURCE_DIR
    monkeypatch.setenv('MAGICLAB_ROOT', str(tmp_path))
    try:
        importlib.reload(config)
        assert config.ROOT_DIR == tmp_path.resolve()
        assert config.RESOURCE_DIR == original
        assert (config.RESOURCE_DIR / 'icons' / 'magiclab.ico').is_file()
    finally:
        monkeypatch.delenv('MAGICLAB_ROOT')
        importlib.reload(config)
