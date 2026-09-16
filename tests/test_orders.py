from datetime import datetime
from decimal import Decimal

import pytest

from app.models import OrderStatus, ServicePrice
from app.repositories.orders import OrderRepository
from app.services.order_service import OrderService, OrderValidationError


def create_order(session, catalog, vehicle_key="sedan", service_keys=("wash",)):
    return OrderService(session).create_order(
        catalog["customer"], catalog[vehicle_key], datetime(2026, 9, 3, 14, 30),
        [catalog[key].id for key in service_keys], 500, "Тестовый заказ",
    )


def test_prices_depend_on_car_class(session, catalog):
    sedan = create_order(session, catalog, "sedan")
    suv = create_order(session, catalog, "suv")
    session.commit()
    assert sedan.total_price == Decimal("1000.00")
    assert suv.total_price == Decimal("1500.00")


def test_create_order(session, catalog):
    order = create_order(session, catalog, service_keys=("wash", "polish"))
    session.commit()
    assert order.id is not None
    assert order.public_number.startswith("ML-202609-")
    assert order.total_price == Decimal("6000.00")
    assert len(order.items) == 2


def test_order_requires_at_least_one_service(session, catalog):
    with pytest.raises(OrderValidationError, match="хотя бы одну"):
        OrderService(session).create_order(
            catalog["customer"], catalog["sedan"], datetime.now(), [], 0
        )


def test_price_snapshot_does_not_change(session, catalog):
    order = create_order(session, catalog)
    session.commit()
    snapshot = order.items[0].price_snapshot
    price = next(item for item in catalog["wash"].prices if item.car_class == catalog["sedan"].car_class)
    price.price = Decimal("9999")
    session.commit()
    session.refresh(order.items[0])
    assert snapshot == Decimal("1000.00")
    assert order.items[0].price_snapshot == Decimal("1000.00")


def test_allowed_status_change(session, catalog):
    order = create_order(session, catalog)
    OrderService(session).change_status(order, OrderStatus.BOOKED, "Подтверждено")
    session.commit()
    assert order.status == OrderStatus.BOOKED


def test_disallowed_status_change(session, catalog):
    order = create_order(session, catalog)
    with pytest.raises(OrderValidationError, match="Недопустимый"):
        OrderService(session).change_status(order, OrderStatus.COMPLETED)


def test_status_history_saved(session, catalog):
    order = create_order(session, catalog)
    OrderService(session).change_status(order, OrderStatus.BOOKED, "Подтверждено")
    session.commit()
    loaded = OrderRepository(session).by_id(order.id)
    assert len(loaded.status_history) == 2
    assert loaded.status_history[-1].old_status == OrderStatus.NEW
    assert loaded.status_history[-1].new_status == OrderStatus.BOOKED


def test_search_by_license_plate(session, catalog):
    order = create_order(session, catalog)
    session.commit()
    result = OrderRepository(session).search("А123ВС")
    assert [item.id for item in result] == [order.id]

