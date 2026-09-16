from __future__ import annotations

from decimal import Decimal

import pytest

from app.database import Database
from app.models import CarClass, Customer, Service, ServicePrice, Vehicle
from app.services.auth_service import AuthService


@pytest.fixture(scope='session')
def qt_app(tmp_path_factory):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QSettings
    from app.main import create_application
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp('settings')))
    app = create_application([])
    yield app
    app.processEvents()


@pytest.fixture
def anonymous_database():
    db = Database("sqlite:///:memory:")
    db.create_schema()
    yield db
    db.dispose()


@pytest.fixture
def database(anonymous_database):
    db = anonymous_database
    with db.session() as session:
        user = AuthService(session).create_admin('test-owner', 'test-owner-password', 'Руководитель тестов')
        session.commit()
        db.sign_in(user)
    return db


@pytest.fixture
def anonymous_session(anonymous_database):
    with anonymous_database.session() as session:
        yield session


@pytest.fixture
def session(database):
    value = database.session()
    yield value
    value.rollback()
    value.close()


@pytest.fixture
def catalog(session):
    customer = Customer(full_name="Иван Петров", phone="+7 (999) 123-45-67", comment="")
    sedan = Vehicle(
        customer=customer, brand="Toyota", model="Camry", license_plate="А123ВС125",
        car_class=CarClass.SEDAN, color="Чёрный", comment="",
    )
    suv = Vehicle(
        customer=customer, brand="Toyota", model="Land Cruiser", license_plate="В456ОР125",
        car_class=CarClass.SUV, color="Белый", comment="",
    )
    wash = Service(name="Мойка", category="Мойка", description="", duration_minutes=60, is_active=True)
    polish = Service(name="Полировка", category="Кузов", description="", duration_minutes=180, is_active=True)
    for service, prices in ((wash, (1000, 1200, 1500, 1600)), (polish, (5000, 6000, 7000, 7500))):
        service.prices = [
            ServicePrice(car_class=car_class, price=Decimal(price))
            for car_class, price in zip(CarClass, prices, strict=True)
        ]
    session.add_all((customer, sedan, suv, wash, polish))
    session.commit()
    return {"customer": customer, "sedan": sedan, "suv": suv, "wash": wash, "polish": polish}
