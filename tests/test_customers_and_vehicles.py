from sqlalchemy.exc import IntegrityError
import pytest

from app.models import CarClass, Customer, Vehicle
from app.repositories.customers import CustomerRepository


def test_create_customer(session):
    customer = CustomerRepository(session).create("Анна Смирнова", "+7 (900) 111-22-33")
    session.commit()
    assert customer.id is not None
    assert customer.full_name == "Анна Смирнова"


def test_duplicate_phone_is_not_allowed(session):
    repository = CustomerRepository(session)
    repository.create("Первый клиент", "+7 (900) 111-22-33")
    session.commit()
    with pytest.raises(ValueError, match="телефоном уже существует"):
        repository.create("Второй клиент", "89001112233")


def test_create_vehicle(session):
    customer = CustomerRepository(session).create("Анна Смирнова", "+7 (900) 111-22-33")
    vehicle = CustomerRepository(session).add_vehicle(
        customer, "Kia", "Sportage", "а111аа125", CarClass.CROSSOVER, "Серый"
    )
    session.commit()
    assert vehicle.id is not None
    assert vehicle.license_plate == "А111АА125"
    assert vehicle.customer_id == customer.id
