from datetime import datetime, timezone

from PySide6.QtCore import QDate, QDateTime, QTime, QTimeZone


def checked_time_zone(identifier: str) -> QTimeZone:
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError('Выберите корректный часовой пояс студии')
    try:
        zone = QTimeZone(identifier.encode('ascii'))
    except (UnicodeError, AttributeError):
        raise ValueError('Выберите корректный часовой пояс студии') from None
    if not zone.isValid():
        raise ValueError('Часовой пояс недоступен. Выберите другой пояс в списке')
    return zone


def local_to_utc(value: datetime, identifier: str) -> datetime:
    zone = checked_time_zone(identifier)
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    qt_value = QDateTime(
        QDate(value.year, value.month, value.day),
        QTime(value.hour, value.minute, value.second),
        zone, QDateTime.TransitionResolution.Reject,
    )
    if not qt_value.isValid():
        raise ValueError(
            f'Время {value:%d.%m.%Y %H:%M} неоднозначно или отсутствует '
            'из-за перевода часов. Проверьте запись и часовой пояс'
        )
    return datetime.fromtimestamp(qt_value.toSecsSinceEpoch(), timezone.utc)
