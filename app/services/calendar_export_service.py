"""Локальный экспорт снимка расписания в iCalendar (RFC 5545)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
from uuid import NAMESPACE_URL, uuid5

from app.models import ORDER_STATUS_LABELS, Order, OrderStatus
from app.repositories.orders import OrderRepository
from app.services.time_zone_service import checked_time_zone, local_to_utc
from app.services.access_service import require


@dataclass(frozen=True)
class CalendarExport:
    content: bytes
    event_count: int
    skipped_cancelled: int


def escape_text(value: str) -> str:
    # Переносы в данных не могут превратиться в отдельные свойства календаря.
    value = str(value).replace('\r\n', '\n').replace('\r', '\n')
    value = ''.join(char for char in value if char in '\n\t' or (ord(char) >= 32 and ord(char) != 127))
    return value.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def fold_line(value: str) -> str:
    """Не более 75 байтов UTF-8, без разрыва многобайтного символа."""
    lines = []
    current = ''
    byte_count = 0
    for char in value:
        char_bytes = len(char.encode('utf-8'))
        if byte_count + char_bytes > 75:
            lines.append(current)
            current, byte_count = ' ', 1
        current += char
        byte_count += char_bytes
    lines.append(current)
    return '\r\n'.join(lines)


def utc_stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError('Для календаря требуется время с часовым поясом')
    return value.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def order_uid(order: Order) -> str:
    # Не зависит от времени записи, статуса или изменяемых данных автомобиля.
    identity = f'urn:magiclab:order:{order.id}:{order.public_number}:{order.created_at.isoformat()}'
    return f'{uuid5(NAMESPACE_URL, identity).hex}@magiclab.local'


def build_calendar(orders: list[Order], timezone_id: str, generated_at: datetime | None = None) -> CalendarExport:
    checked_time_zone(timezone_id)
    stamp = utc_stamp(generated_at or datetime.now(timezone.utc))
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0',
             'PRODID:-//Magic Lab Detailing//MagicLab Manager//RU',
             'CALSCALE:GREGORIAN', 'X-WR-CALNAME:Magic Lab Detailing']
    count = skipped = 0
    for order in sorted(orders, key=lambda entry: (entry.scheduled_at, entry.id)):
        if order.status == OrderStatus.CANCELLED:
            skipped += 1
            continue
        if order.total_duration_minutes <= 0:
            raise ValueError(f'У заказа {order.public_number} не указана положительная длительность')
        start = local_to_utc(order.scheduled_at, timezone_id)
        try:
            end = start + timedelta(minutes=order.total_duration_minutes)
        except OverflowError:
            raise ValueError(f'Слишком большая длительность заказа {order.public_number}') from None
        vehicle = f'{order.vehicle.brand} {order.vehicle.model} · {order.vehicle.license_plate}'
        # Явный белый список: никаких контактов, ФИО, цен и внутренних комментариев.
        description = '\n'.join([
            f'Заказ: {order.public_number}', f'Автомобиль: {vehicle}',
            f'Статус: {ORDER_STATUS_LABELS[order.status]}',
            f'Часовой пояс студии: {timezone_id}',
            'Услуги:', *[f'• {item.service_name_snapshot}' for item in order.items],
            f'Примерная длительность: {order.total_duration_minutes} мин.',
            'Окончание рассчитано без учёта перерывов и ночного хранения.',
            'Копия расписания на момент экспорта. Изменения автоматически не поступают.',
        ])
        lines.extend([
            'BEGIN:VEVENT', f'UID:{order_uid(order)}', f'DTSTAMP:{stamp}',
            f'DTSTART:{utc_stamp(start)}', f'DTEND:{utc_stamp(end)}',
            f'SUMMARY:{escape_text(f"Magic Lab · {order.public_number} · {vehicle}")}',
            f'DESCRIPTION:{escape_text(description)}', 'CLASS:PRIVATE',
            'STATUS:TENTATIVE' if order.status == OrderStatus.NEW else 'STATUS:CONFIRMED',
            'TRANSP:OPAQUE', 'END:VEVENT',
        ])
        count += 1
    lines.append('END:VCALENDAR')
    content = ('\r\n'.join(fold_line(line) for line in lines) + '\r\n').encode('utf-8')
    return CalendarExport(content, count, skipped)


class CalendarExportService:
    def __init__(self, session):
        self.session = session

    def prepare(self, date_from: date, date_to: date, timezone_id: str) -> CalendarExport:
        require(self.session, 'calendar_export')
        if date_from > date_to:
            raise ValueError('Начало периода не может быть позже окончания')
        orders = OrderRepository(self.session).search(date_from=date_from, date_to=date_to)
        return build_calendar(orders, timezone_id)


def save_calendar(path: Path, export: CalendarExport) -> None:
    """Атомарная запись: при ошибке старый экспорт остаётся неповреждённым."""
    if export.event_count == 0:
        raise ValueError('В выбранном периоде нет заказов для экспорта')
    path = Path(path)
    if path.suffix.lower() != '.ics':
        raise ValueError('Сохраните календарь с расширением .ics')
    descriptor, temporary = tempfile.mkstemp(prefix='.magiclab-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(export.content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
