from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app.models import Base, AuditLog
from app.services.access_service import require
from app.services.audit_service import record


class BackupError(RuntimeError):
    pass


def verify_sqlite(path: Path) -> None:
    if not path.is_file():
        raise BackupError("Файл резервной копии не найден")
    if path.stat().st_size == 0:
        raise BackupError("Файл резервной копии пуст")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise BackupError('Версия резервной копии не поддерживается')
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError("Файл не является исправной базой MagicLab Manager")
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name, table in Base.metadata.tables.items():
                if version < 3 and name in ('vehicle_inspections', 'damage_marks', 'inspection_photos'):
                    continue
                if version < 2 and name == 'audit_log':
                    continue
                if name not in tables:
                    raise BackupError("В копии отсутствуют таблицы MagicLab Manager")
                columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')}
                expected = {column.name for column in table.columns}
                if version < 2:
                    expected -= {'role', 'auth_version'} if name == 'users' else {'assigned_master_id'} if name == 'orders' else set()
                if not expected.issubset(columns):
                    raise BackupError("Структура копии несовместима с этой версией программы")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise BackupError("В копии нарушены связи данных")
            if version >= 2:
                if connection.execute("SELECT 1 FROM users WHERE role NOT IN ('OWNER','ADMIN','MASTER') OR auth_version < 1 LIMIT 1").fetchone():
                    raise BackupError('В копии некорректные роли пользователей')
                if connection.execute('SELECT 1 FROM users LIMIT 1').fetchone() and not connection.execute("SELECT 1 FROM users WHERE role='OWNER' AND is_active=1 LIMIT 1").fetchone():
                    raise BackupError('В копии нет активного руководителя')
            if version >= 3:
                from app.services.inspection_service import InspectionService
                for row in connection.execute('SELECT view, normalized_x, normalized_y, body_element, damage_type, severity, comment, paint_thickness_um FROM damage_marks'):
                    try:
                        InspectionService.validate_mark(dict(zip(('view', 'normalized_x', 'normalized_y', 'body_element', 'damage_type', 'severity', 'comment', 'paint_thickness_um'), row)))
                    except ValueError as exc:
                        raise BackupError(f'В копии некорректное замечание осмотра: {exc}') from exc
                if connection.execute('SELECT 1 FROM inspection_photos p JOIN damage_marks m ON m.id=p.damage_mark_id WHERE p.inspection_id<>m.inspection_id LIMIT 1').fetchone():
                    raise BackupError('Фотография привязана к замечанию другого осмотра')
    except sqlite3.DatabaseError as exc:
        raise BackupError("Не удалось проверить файл резервной копии") from exc


def _create_backup_file(source: Path, backup_dir: Path, prefix: str = "magiclab") -> Path:
    if not source.is_file():
        raise BackupError("Рабочая база данных не найдена")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = backup_dir / f"{prefix}_{stamp}.db"
    try:
        with closing(sqlite3.connect(source)) as source_db, closing(sqlite3.connect(destination)) as target_db:
            source_db.backup(target_db)
        verify_sqlite(destination)
        return destination
    except (sqlite3.DatabaseError, OSError, BackupError) as exc:
        destination.unlink(missing_ok=True)
        raise BackupError("Не удалось создать резервную копию") from exc


def _restore_backup_file(current_db: Path, backup_file: Path, backup_dir: Path, prepare) -> tuple[Path, Path]:
    if current_db.resolve() == backup_file.resolve():
        raise BackupError("Выберите резервную копию, а не текущую рабочую базу")
    verify_sqlite(backup_file)
    safety = _create_backup_file(current_db, backup_dir, prefix="before_restore")
    descriptor, name = tempfile.mkstemp(prefix='.magiclab-restore-', suffix='.db', dir=current_db.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copy2(backup_file, temporary)
        prepare(temporary)
        verify_sqlite(temporary)
        os.replace(temporary, current_db)
        return current_db, safety
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise BackupError("Не удалось восстановить базу данных") from exc


def create_backup(source: Path, backup_dir: Path, prefix: str = 'magiclab', *, session=None) -> Path:
    require(session, 'backup')
    from app.services.backup_archive import create_zip
    destination = create_zip(Path(source), Path(backup_dir), prefix)
    record(session, 'Резервная копия', f'Создана и проверена копия {destination.name}')
    return destination


def restore_backup(current_db: Path, backup_file: Path, backup_dir: Path, *, session=None) -> tuple[Path, Path]:
    actor = require(session, 'restore')
    database = session.info['database']
    from app.services.backup_archive import verify_backup, restore_zip_or_legacy
    verify_backup(Path(backup_file))
    record(session, 'Запрос восстановления', f'Руководитель подтвердил восстановление из {Path(backup_file).name}')
    session.commit()
    from sqlalchemy import select
    journal = [dict(row) for row in session.execute(select(AuditLog.__table__)).mappings()]
    session.close()
    database.dispose()

    def prepare(temporary):
        from app.database import Database
        from app.migrations import upgrade_schema
        staging = Database(f'sqlite:///{temporary.resolve().as_posix()}')
        try:
            upgrade_schema(staging.engine, Path(backup_dir), backup_existing=False)
            with staging.session() as target:
                existing = set(target.scalars(select(AuditLog.event_id)))
                for row in journal:
                    if row['event_id'] not in existing:
                        # Снимки имени сохраняются; id пользователя в старой копии может принадлежать другой записи.
                        target.add(AuditLog(**{key: value for key, value in row.items() if key not in ('id', 'user_id')}, user_id=None))
                target.add(AuditLog(user_id=None, username=actor.username, full_name=actor.full_name,
                    action='Восстановление базы', description=f'Восстановлена копия {Path(backup_file).name}; журнал текущей базы сохранён'))
                target.commit()
        finally:
            staging.dispose()

    result = restore_zip_or_legacy(Path(current_db), Path(backup_file), Path(backup_dir), prepare)
    database.sign_out()
    return result
