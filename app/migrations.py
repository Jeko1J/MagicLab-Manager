"""Последовательные миграции схемы SQLite."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 3


def upgrade_schema(engine, backup_dir: Path, backup_existing: bool = True) -> Path | None:
    with engine.connect() as connection:
        version = connection.exec_driver_sql('PRAGMA user_version').scalar_one()
        tables = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
    if version > SCHEMA_VERSION:
        raise ValueError('Эта база создана более новой версией MagicLab Manager')
    backup = None
    if backup_existing and 'users' in tables and version < SCHEMA_VERSION:
        path = engine.url.database
        if path and path != ':memory:':
            backup_dir.mkdir(parents=True, exist_ok=True)
            prefix = 'before_roles' if version < 2 else 'before_inspection'
            backup = backup_dir / f'{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}.db'
            with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Не удалось проверить страховочную копию перед обновлением')
    # BEGIN IMMEDIATE включает DDL в явную транзакцию sqlite3.
    with engine.connect() as connection:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            if 'users' in tables:
                columns = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info(users)')}
                if 'role' not in columns:
                    connection.exec_driver_sql("ALTER TABLE users ADD COLUMN role VARCHAR(6) NOT NULL DEFAULT 'MASTER'")
                    # Раньше все локальные пользователи имели полный доступ.
                    connection.exec_driver_sql("UPDATE users SET role='OWNER'")
                if 'auth_version' not in columns:
                    connection.exec_driver_sql('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1')
            if 'orders' in tables:
                columns = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info(orders)')}
                if 'assigned_master_id' not in columns:
                    connection.exec_driver_sql('ALTER TABLE orders ADD COLUMN assigned_master_id INTEGER REFERENCES users(id) ON DELETE RESTRICT')
                connection.exec_driver_sql('CREATE INDEX IF NOT EXISTS ix_orders_assigned_master_id ON orders(assigned_master_id)')
            from app.models import Base
            Base.metadata.create_all(connection)
            if version < SCHEMA_VERSION:
                from app.models import AuditLog
                connection.execute(AuditLog.__table__.insert().values(user_id=None, username='Система', full_name='MagicLab Manager',
                    action='Обновление базы' if tables else 'Создание базы',
                    description='Схема 3: карта осмотра ЛКП, замечания и фотографии; роли и журнал сохранены'))
            connection.exec_driver_sql(f'PRAGMA user_version={SCHEMA_VERSION}')
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return backup
