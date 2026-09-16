from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import BACKUP_DIR, database_url, ensure_directories
from app.models import Base, CarClass, Service, ServicePrice


DEMO_SERVICES: tuple[tuple[str, str, str, int, tuple[int, int, int, int]], ...] = (
    ("Детейлинг-мойка", "Мойка", "Комплексная безопасная мойка кузова и дисков.", 120, (2500, 3000, 3500, 3500)),
    ("Химчистка салона", "Салон", "Глубокая очистка салона и багажного отделения.", 600, (14000, 16500, 19000, 19000)),
    ("Полировка кузова", "Кузов", "Восстановительная полировка лакокрасочного покрытия.", 720, (18000, 22000, 26000, 26000)),
    ("Керамическое покрытие", "Защита кузова", "Нанесение защитного керамического состава.", 480, (22000, 26000, 30000, 30000)),
    ("Защитная полиуретановая плёнка", "Защита кузова", "Оклейка зон риска прозрачной полиуретановой плёнкой.", 960, (65000, 75000, 85000, 85000)),
    ("Полировка фар", "Оптика", "Восстановление прозрачности передней оптики.", 90, (3000, 3000, 3500, 3500)),
    ("Антидождь", "Стёкла", "Гидрофобное покрытие лобового стекла.", 45, (1800, 2000, 2200, 2200)),
    ("Озонация салона", "Салон", "Удаление неприятных запахов методом озонации.", 60, (1500, 1800, 2000, 2000)),
    ("Удаление битума и металлических вкраплений", "Кузов", "Глубокая очистка кузова перед защитными работами.", 180, (4500, 5500, 6500, 6500)),
    ("Защитное покрытие кожи", "Салон", "Очистка и нанесение защитного состава на кожаные элементы.", 150, (5000, 6000, 7000, 7000)),
)


class Database:
    def __init__(self, url: str | None = None) -> None:
        ensure_directories()
        self.url = url or database_url()
        self.actor_id = None
        self.auth_version = None
        self.auth_generation = 0
        self.migration_backup = None
        kwargs: dict = {"future": True}
        if self.url == "sqlite:///:memory:":
            kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.engine: Engine = create_engine(self.url, **kwargs)
        if self.url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_foreign_keys)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    @staticmethod
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.create_function("lower", 1, lambda value: value.casefold() if value is not None else None)
        dbapi_connection.create_function("phone_digits", 1, lambda value: "".join(ch for ch in (value or "") if ch.isdigit()))
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        from app.migrations import upgrade_schema
        from pathlib import Path
        location = self.engine.url.database
        backup_dir = BACKUP_DIR if url_is_default(self.url) else (Path(location).parent / 'backups' if location and location != ':memory:' else BACKUP_DIR)
        self.migration_backup = upgrade_schema(self.engine, backup_dir)

    def session(self) -> Session:
        return self.session_factory(info={'actor_id': self.actor_id, 'auth_version': self.auth_version,
                                          'database': self, 'auth_generation': self.auth_generation})

    def sign_in(self, user) -> None:
        self.auth_generation += 1
        self.actor_id = user.id
        self.auth_version = user.auth_version

    def sign_out(self) -> None:
        self.auth_generation += 1
        self.actor_id = self.auth_version = None

    def dispose(self) -> None:
        self.engine.dispose()

    def seed_demo_services(self) -> None:
        with self.session() as session:
            if session.scalar(select(Service.id).limit(1)) is not None:
                return
            classes = list(CarClass)
            for name, category, description, duration, values in DEMO_SERVICES:
                service = Service(
                    name=name,
                    category=category,
                    description=description,
                    duration_minutes=duration,
                    is_active=True,
                )
                service.prices = [
                    ServicePrice(car_class=car_class, price=Decimal(value))
                    for car_class, value in zip(classes, values, strict=True)
                ]
                session.add(service)
            session.commit()


def url_is_default(url):
    return url == database_url()
