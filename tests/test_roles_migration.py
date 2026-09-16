from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import select

from app.database import Database
from app.models import AuditLog, Base, Order, User, UserRole
from app.services.auth_service import AuthService, hash_password
from app.services.backup_service import create_backup, restore_backup, verify_sqlite, BackupError


def legacy_database(path):
    password_hash = hash_password('legacy-password')
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript('''
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL);
        CREATE TABLE customers (id INTEGER PRIMARY KEY, full_name TEXT, phone TEXT, comment TEXT, created_at DATETIME, updated_at DATETIME);
        CREATE TABLE vehicles (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), brand TEXT, model TEXT,
            license_plate TEXT, car_class TEXT, color TEXT, comment TEXT);
        CREATE TABLE services (id INTEGER PRIMARY KEY, name TEXT, category TEXT, description TEXT, duration_minutes INTEGER, is_active BOOLEAN);
        CREATE TABLE service_prices (id INTEGER PRIMARY KEY, service_id INTEGER REFERENCES services(id), car_class TEXT, price NUMERIC);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, public_number TEXT UNIQUE, customer_id INTEGER REFERENCES customers(id),
            vehicle_id INTEGER REFERENCES vehicles(id), scheduled_at DATETIME, status TEXT, total_price NUMERIC, total_duration_minutes INTEGER,
            prepayment NUMERIC, comment TEXT, created_at DATETIME, updated_at DATETIME);
        CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), service_id INTEGER REFERENCES services(id),
            service_name_snapshot TEXT, price_snapshot NUMERIC, duration_snapshot INTEGER);
        CREATE TABLE status_history (id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), old_status TEXT,
            new_status TEXT, changed_at DATETIME, comment TEXT);
        PRAGMA user_version=1;
        INSERT INTO customers VALUES(1,'Старый клиент','+7 (900) 111-22-33','','2026-09-01','2026-09-01');
        INSERT INTO vehicles VALUES(1,1,'Toyota','Camry','А001АА125','SEDAN','Белый','');
        INSERT INTO services VALUES(1,'Мойка','Мойка','',60,1);
        INSERT INTO service_prices VALUES(1,1,'SEDAN',1000);
        INSERT INTO orders VALUES(1,'ML-202609-0001',1,1,'2026-09-04 10:00:00','BOOKED',900,60,100,'Старое примечание','2026-09-01','2026-09-01');
        INSERT INTO order_items VALUES(1,1,1,'Старое название мойки',900,60);
        INSERT INTO status_history VALUES(1,1,'NEW','BOOKED','2026-09-01','Запись подтверждена');
        ''')
        connection.execute('INSERT INTO users VALUES(1,?,?,?,?,?)', ('legacy-owner', password_hash, 'Прежний руководитель', 1, '2026-09-01'))
        connection.commit()
    return password_hash


def test_migration_keeps_data_passwords_and_creates_backup(tmp_path):
    path = tmp_path / 'legacy.db'
    original_hash = legacy_database(path)
    verify_sqlite(path)
    db = Database(f'sqlite:///{path.as_posix()}')
    db.create_schema()
    backup = db.migration_backup
    assert backup and backup.is_file()
    with closing(sqlite3.connect(backup)) as connection:
        assert 'role' not in {row[1] for row in connection.execute('PRAGMA table_info(users)')}
    with db.session() as session:
        user = AuthService(session).authenticate('legacy-owner', 'legacy-password')
        assert user.role == UserRole.OWNER and user.password_hash == original_hash
        assert session.get(Order, 1).assigned_master_id is None
        assert session.get(Order, 1).items[0].service_name_snapshot == 'Старое название мойки'
        assert session.get(Order, 1).items[0].price_snapshot == 900
    db.create_schema()
    assert db.migration_backup is None
    assert len(list((tmp_path / 'backups').glob('before_roles_*.db'))) == 1
    verify_sqlite(path)
    db.dispose()


def test_failed_migration_rolls_back_ddl(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    legacy_database(path)
    db = Database(f'sqlite:///{path.as_posix()}')
    def fail(*args, **kwargs):
        raise RuntimeError('simulated DDL failure')
    monkeypatch.setattr(Base.metadata, 'create_all', fail)
    with pytest.raises(RuntimeError):
        db.create_schema()
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 1
        assert 'role' not in {row[1] for row in connection.execute('PRAGMA table_info(users)')}
        assert connection.execute('SELECT count(*) FROM orders').fetchone()[0] == 1
    assert len(list((tmp_path / 'backups').glob('before_roles_*.db'))) == 1
    db.dispose()


def test_future_schema_is_not_downgraded(tmp_path):
    path = tmp_path / 'future.db'
    legacy_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('PRAGMA user_version=999')
    db = Database(f'sqlite:///{path.as_posix()}')
    with pytest.raises(ValueError, match='новой версией'):
        db.create_schema()
    with pytest.raises(BackupError):
        verify_sqlite(path)
    db.dispose()


def test_restore_legacy_copy_migrates_and_preserves_current_journal(tmp_path):
    old = tmp_path / 'old.db'
    legacy_database(old)
    current = tmp_path / 'current.db'
    db = Database(f'sqlite:///{current.as_posix()}')
    db.create_schema()
    with db.session() as session:
        user = AuthService(session).create_admin('current-owner', 'password', 'Текущий руководитель')
        session.commit()
        db.sign_in(user)
        event_ids = set(session.scalars(select(AuditLog.event_id)))
    with db.session() as session:
        restored, safety = restore_backup(current, old, tmp_path / 'copies', session=session)
    assert restored == current and safety.is_file()
    assert db.actor_id is None
    with db.session() as session:
        assert AuthService(session).authenticate('legacy-owner', 'legacy-password')
        assert event_ids <= set(session.scalars(select(AuditLog.event_id)))
        restored_event = session.scalar(select(AuditLog).where(AuditLog.action == 'Восстановление базы'))
        assert restored_event.username == 'current-owner' and restored_event.full_name == 'Текущий руководитель'
        assert restored_event.user_id is None
    verify_sqlite(current)
    db.dispose()


def test_restore_failure_keeps_current_database_and_safety(tmp_path, monkeypatch):
    old = tmp_path / 'old.db'
    legacy_database(old)
    current = tmp_path / 'current.db'
    db = Database(f'sqlite:///{current.as_posix()}')
    db.create_schema()
    with db.session() as session:
        user = AuthService(session).create_admin('current-owner', 'password', 'Руководитель')
        session.commit()
        db.sign_in(user)
    import app.services.backup_service as module
    def fail(*args):
        raise PermissionError('simulated replace failure')
    monkeypatch.setattr(module.os, 'replace', fail)
    with db.session() as session:
        with pytest.raises(BackupError):
            restore_backup(current, old, tmp_path / 'copies', session=session)
    with db.session() as session:
        assert AuthService(session).authenticate('current-owner', 'password')
        assert session.scalar(select(Order.id)) is None
    assert list((tmp_path / 'copies').glob('before_restore_*.zip'))
    assert not list(tmp_path.glob('.magiclab-restore-*.db'))
    db.dispose()
