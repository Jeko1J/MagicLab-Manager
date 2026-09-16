from datetime import date, datetime
from decimal import Decimal

from app.database import Database
from app.models import OrderStatus
from app.repositories.services import ServiceRepository
from app.services.backup_service import create_backup, verify_sqlite
from app.services.backup_archive import verify_backup
from app.services.order_service import OrderService
from app.services.statistics_service import StatisticsService
from app.services.auth_service import AuthService


def test_disable_and_restore_service(session, catalog):
    repository = ServiceRepository(session)
    repository.disable(catalog["wash"].id)
    session.commit()
    assert repository.by_id(catalog["wash"].id).is_active is False
    repository.enable(catalog["wash"].id)
    session.commit()
    assert repository.by_id(catalog["wash"].id).is_active is True


def test_statistics_calculation(session, catalog):
    order = OrderService(session).create_order(
        catalog["customer"], catalog["sedan"], datetime.now(),
        [catalog["wash"].id], 0,
    )
    service = OrderService(session)
    service.change_status(order, OrderStatus.BOOKED)
    service.change_status(order, OrderStatus.IN_PROGRESS)
    service.change_status(order, OrderStatus.READY)
    service.change_status(order, OrderStatus.COMPLETED)
    session.commit()
    result = StatisticsService(session).calculate(date.today(), date.today())
    assert result.created == 1
    assert result.completed == 1
    assert result.revenue == Decimal("1000.00")
    assert result.popular_services[0] == ("Мойка", 1)


def test_create_backup(tmp_path):
    source = tmp_path / "magiclab.db"
    db = Database(f"sqlite:///{source.as_posix()}")
    db.create_schema()
    db.seed_demo_services()
    with db.session() as session:
        user = AuthService(session).create_admin('owner', 'test-password', 'Руководитель')
        session.commit()
        db.sign_in(user)
    with db.session() as session:
        destination = create_backup(source, tmp_path / 'backups', session=session)
        session.commit()
    db.dispose()
    assert destination.is_file()
    assert destination != source
    assert destination.suffix == '.zip'
    verify_backup(destination)
