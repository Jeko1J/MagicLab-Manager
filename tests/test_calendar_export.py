from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models import OrderStatus
from app.services.calendar_export_service import (
    CalendarExportService, build_calendar, escape_text, fold_line, order_uid, save_calendar,
)
from app.services.order_service import OrderService
from app.services.time_zone_service import local_to_utc


def make_order(session, catalog, scheduled=datetime(2026, 9, 4, 10, 30)):
    return OrderService(session).create_order(
        catalog['customer'], catalog['sedan'], scheduled,
        [catalog['wash'].id, catalog['polish'].id], 0, 'Секретный комментарий администратора',
    )


def unfolded(payload):
    return payload.decode('utf-8').replace('\r\n ', '').replace('\r\n\t', '')


def test_one_event_utc_duration_and_privacy(session, catalog):
    order = make_order(session, catalog)
    result = build_calendar([order], 'Asia/Vladivostok', datetime(2026, 9, 1, tzinfo=timezone.utc))
    text = unfolded(result.content)
    assert result.event_count == 1
    assert 'DTSTART:20260904T003000Z\r\n' in text
    assert 'DTEND:20260904T043000Z\r\n' in text
    assert 'DTSTAMP:20260901T000000Z\r\n' in text
    assert 'Toyota Camry' in text and 'А123ВС125' in text
    assert 'Мойка' in text and 'Полировка' in text
    assert 'STATUS:TENTATIVE' in text
    for private in (catalog['customer'].full_name, catalog['customer'].phone, order.comment, '6000', 'ATTENDEE:', 'ORGANIZER:'):
        assert private not in text


def test_period_inclusive_sorted_and_cancelled(session, catalog):
    start = datetime(2026, 9, 4)
    first = make_order(session, catalog, start)
    make_order(session, catalog, datetime(2026, 9, 4, 23, 59, 59))
    cancelled = make_order(session, catalog, start + timedelta(hours=12))
    OrderService(session).change_status(cancelled, OrderStatus.CANCELLED)
    make_order(session, catalog, start - timedelta(seconds=1))
    make_order(session, catalog, start + timedelta(days=1))
    session.flush()
    result = CalendarExportService(session).prepare(date(2026, 9, 4), date(2026, 9, 4), 'Europe/Moscow')
    text = unfolded(result.content)
    assert result.event_count == 2
    assert result.skipped_cancelled == 1
    assert text.count('BEGIN:VEVENT\r\n') == 2
    assert text.index(order_uid(first)) < text.index('DTSTART:20260904T205900Z')
    assert order_uid(cancelled) not in text


def test_multi_day_range_and_end_next_day(session, catalog):
    order = make_order(session, catalog, datetime(2026, 9, 4, 23))
    make_order(session, catalog, datetime(2026, 9, 5, 10))
    result = CalendarExportService(session).prepare(date(2026, 9, 4), date(2026, 9, 5), 'UTC')
    assert result.event_count == 2
    assert 'DTEND:20260905T030000Z' in unfolded(result.content)


def test_uid_stable_after_edit_and_restore_identity(session, catalog):
    order = make_order(session, catalog)
    before = order_uid(order)
    order.scheduled_at += timedelta(days=3)
    order.vehicle.model = 'Corolla'
    order.comment = 'Другой комментарий'
    OrderService(session).change_status(order, OrderStatus.BOOKED)
    assert order_uid(order) == before
    assert 'STATUS:CONFIRMED' in unfolded(build_calendar([order], 'UTC').content)


def test_snapshot_service_names_are_used(session, catalog):
    order = make_order(session, catalog)
    catalog['wash'].name = 'Новое название прайса'
    assert 'Новое название прайса' not in unfolded(build_calendar([order], 'UTC').content)


def test_text_escaping_folding_and_line_injection(session, catalog):
    order = make_order(session, catalog)
    order.items[0].service_name_snapshot = 'Защита, плёнка; стекло\\кузов\r\nATTENDEE:mailto:test@example.com ' + 'Очень длинная услуга 🚘 ' * 30
    payload = build_calendar([order], 'UTC').content
    assert payload.startswith(b'BEGIN:VCALENDAR\r\n')
    assert payload.endswith(b'END:VCALENDAR\r\n')
    assert b'\n' not in payload.replace(b'\r\n', b'')
    for line in payload.split(b'\r\n'):
        assert len(line) <= 75
        line.decode('utf-8')  # folded line never splits a UTF-8 character
    text = unfolded(payload)
    assert 'Защита\\, плёнка\\; стекло\\\\кузов\\nATTENDEE:' in text
    assert '\r\nATTENDEE:' not in text
    assert text.count('BEGIN:VEVENT') == 1
    assert escape_text('a\x00\x7fb') == 'ab'


@pytest.mark.parametrize('zone,hour', [('Asia/Vladivostok', 0), ('Europe/Moscow', 7), ('UTC', 10)])
def test_timezones(zone, hour):
    assert local_to_utc(datetime(2026, 9, 4, 10), zone) == datetime(2026, 9, 4, hour, tzinfo=timezone.utc)


def test_dst_uses_offset_for_event_date():
    assert local_to_utc(datetime(2026, 1, 15, 12), 'Europe/Berlin').hour == 11
    assert local_to_utc(datetime(2026, 7, 15, 12), 'Europe/Berlin').hour == 10


@pytest.mark.parametrize('value', [datetime(2026, 3, 29, 2, 30), datetime(2026, 10, 25, 2, 30)])
def test_dst_ambiguous_or_missing_time_rejected(value):
    with pytest.raises(ValueError, match='перевода часов'):
        local_to_utc(value, 'Europe/Berlin')


@pytest.mark.parametrize('zone', ['Not/AZone', '', 'Несуществующий пояс', None])
def test_invalid_timezone(zone):
    with pytest.raises(ValueError, match='пояс'):
        build_calendar([], zone)


def test_invalid_period(session):
    with pytest.raises(ValueError, match='Начало периода'):
        CalendarExportService(session).prepare(date(2026, 9, 5), date(2026, 9, 4), 'UTC')


def test_zero_duration_rejected(session, catalog):
    order = make_order(session, catalog)
    order.total_duration_minutes = 0
    with pytest.raises(ValueError, match='длительность'):
        build_calendar([order], 'UTC')


def test_empty_export_does_not_overwrite(tmp_path):
    path = tmp_path / 'schedule.ics'
    path.write_bytes(b'previous file')
    with pytest.raises(ValueError, match='нет заказов'):
        save_calendar(path, build_calendar([], 'UTC'))
    assert path.read_bytes() == b'previous file'


def test_atomic_file_write(session, catalog, tmp_path, monkeypatch):
    import app.services.calendar_export_service as module
    result = build_calendar([make_order(session, catalog)], 'UTC')
    path = tmp_path / 'schedule.ics'
    save_calendar(path, result)
    assert path.read_bytes() == result.content
    assert list(tmp_path.glob('.magiclab-*.tmp')) == []
    def deny_replace(*args):
        raise PermissionError('read-only target')
    monkeypatch.setattr(module.os, 'replace', deny_replace)
    with pytest.raises(PermissionError):
        save_calendar(path, result)
    assert path.read_bytes() == result.content
    assert list(tmp_path.glob('.magiclab-*.tmp')) == []
