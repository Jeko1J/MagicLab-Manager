from datetime import date
from decimal import Decimal
from sqlalchemy import select
import pytest

from app.database import Database
from app.models import Order, OrderStatus, User
from app.services.auth_service import AuthService
from app.services.master_order_service import MasterOrderService
from app.services.statistics_service import StatisticsService
from tools.report_demo import create_demo, seed_report_data, DEMO_PASSWORD


def test_report_demo_statuses_calculation_and_chronology(anonymous_database):
    db = anonymous_database
    manifest = seed_report_data(db, date(2026, 9, 4))
    assert manifest['counts']['orders'] == 18
    assert set(manifest['counts']['statuses']) == {status.value for status in OrderStatus}
    with db.session() as session:
        sample = session.get(Order, manifest['sample_order_id'])
        assert (sample.total_price, sample.prepayment, sample.total_duration_minutes) == (Decimal('5000'), Decimal('1000'), 165)
        for order in session.scalars(select(Order)):
            dates = [item.changed_at for item in order.status_history]
            assert dates == sorted(dates)
            assert 'Учебные данные' in order.comment
            if order.status in (OrderStatus.READY, OrderStatus.COMPLETED):
                assert dates[-1].date() < date(2026, 9, 4)
        result = StatisticsService(session).calculate(date(2026, 8, 23), date(2026, 9, 7))
        assert result.created == 18 and result.completed == 4 and result.cancelled == 2
        assert result.revenue == Decimal('4300') + Decimal('48000') + Decimal('19000') + Decimal('10500')
        assert result.average_check == Decimal('20450')


def test_report_demo_masters_have_separate_assignments(anonymous_database):
    db = anonymous_database
    manifest = seed_report_data(db, date(2026, 9, 4))
    with db.session() as session:
        master = AuthService(session).authenticate('demo-master', DEMO_PASSWORD)
        session.commit()
    db.sign_in(master)
    with db.session() as session:
        rows = MasterOrderService(session).list_orders(current_only=False)
        expected = {item['id'] for item in manifest['orders'] if item['master'] == 'demo-master'}
        assert {item.id for item in rows} == expected


def test_report_demo_refuses_existing_database(tmp_path):
    create_demo(tmp_path, date(2026, 9, 4))
    original = (tmp_path / 'data/magiclab.db').read_bytes()
    with pytest.raises(ValueError, match='уже существует'):
        create_demo(tmp_path, date(2026, 9, 4))
    assert (tmp_path / 'data/magiclab.db').read_bytes() == original
