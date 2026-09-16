from decimal import Decimal

import pytest

from app.services.calculation_service import (
    CalculationError,
    CalculationLine,
    calculate,
    validate_prepayment,
)


def test_calculation_one_service():
    result = calculate([CalculationLine(1, "Мойка", Decimal("2500"), 120)])
    assert result.total_price == Decimal("2500.00")
    assert result.total_duration_minutes == 120


def test_calculation_multiple_services():
    result = calculate([
        CalculationLine(1, "Мойка", 2500, 120),
        CalculationLine(2, "Полировка", 18000, 720),
    ])
    assert result.total_price == Decimal("20500.00")
    assert result.total_duration_minutes == 840


def test_empty_order_calculation():
    result = calculate([])
    assert result.total_price == Decimal("0.00")
    assert result.total_duration_minutes == 0


def test_negative_price_rejected():
    with pytest.raises(CalculationError, match="не может быть отрицательной"):
        calculate([CalculationLine(1, "Ошибка", -1, 10)])


@pytest.mark.parametrize("payment,total", [(-1, 100), (101, 100)])
def test_invalid_prepayment_rejected(payment, total):
    with pytest.raises(CalculationError):
        validate_prepayment(payment, total)

