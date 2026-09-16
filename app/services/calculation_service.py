from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


@dataclass(frozen=True)
class CalculationLine:
    service_id: int
    name: str
    price: Decimal
    duration_minutes: int


@dataclass(frozen=True)
class CalculationResult:
    lines: tuple[CalculationLine, ...]
    total_price: Decimal
    total_duration_minutes: int


class CalculationError(ValueError):
    pass


def money(value) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CalculationError("Некорректная стоимость услуги") from exc
    if not result.is_finite():
        raise CalculationError("Некорректная стоимость услуги")
    if result < 0:
        raise CalculationError("Стоимость услуги не может быть отрицательной")
    return result


def calculate(lines: Iterable[CalculationLine]) -> CalculationResult:
    items: list[CalculationLine] = []
    total = Decimal("0.00")
    minutes = 0
    for line in lines:
        price = money(line.price)
        if line.duration_minutes < 0:
            raise CalculationError("Продолжительность услуги не может быть отрицательной")
        duration = int(line.duration_minutes)
        items.append(CalculationLine(line.service_id, line.name, price, duration))
        total += price
        minutes += duration
    return CalculationResult(tuple(items), total.quantize(Decimal("0.00")), minutes)


def validate_prepayment(prepayment, total_price) -> Decimal:
    try:
        payment = money(prepayment)
    except CalculationError as exc:
        raise CalculationError("Предоплата должна быть неотрицательным числом") from exc
    total = money(total_price)
    if payment > total:
        raise CalculationError("Предоплата не может превышать стоимость заказа")
    return payment
