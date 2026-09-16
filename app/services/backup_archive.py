"""Полные ZIP-копии. Извлечение только проверенных относительных путей, без extractall."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app.config import APP_NAME, APP_VERSION
from app.migrations import SCHEMA_VERSION
from app.services.inspection_service import safe_photo_path, load_photo

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_photos(db, data_dir):
    from app.services.backup_service import BackupError
    with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'inspection_photos' not in tables:
            return []
        relatives = [row[0] for row in connection.execute('SELECT file_path FROM inspection_photos')]
    for relative in relatives:
        try:
            path = safe_photo_path(data_dir, relative)
            load_photo(path)
        except (ValueError, OSError) as exc:
            raise BackupError(f'Проверка фото не пройдена: {relative}. {exc}') from exc
    return relatives


def create_zip(source, backup_dir, prefix='magiclab', *, allow_incomplete=False):
    from app.services.backup_service import BackupError, _create_backup_file
    source, backup_dir = Path(source), Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f'{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}.zip'
    try:
        # Системный temp помогает уложиться в MAX_PATH при проверке фото.
        with tempfile.TemporaryDirectory(prefix='ml-backup-') as folder:
            stage = Path(folder)
            snapshot = _create_backup_file(source, stage)
            missing = []
            if allow_incomplete:
                with closing(sqlite3.connect(snapshot)) as connection:
                    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    relatives = [row[0] for row in connection.execute('SELECT file_path FROM inspection_photos')] if 'inspection_photos' in tables else []
                for relative in relatives:
                    try:
                        load_photo(safe_photo_path(source.parent, relative))
                    except (ValueError, OSError):
                        missing.append(relative)
            else:
                relatives = check_photos(snapshot, source.parent)
            files = {'database.db': snapshot}
            # Только управляемые фотографии, на которые ссылается этот снимок БД.
            files.update({relative: safe_photo_path(source.parent, relative) for relative in relatives
                          if safe_photo_path(source.parent, relative).is_file()})
            if sum(path.stat().st_size for path in files.values()) > MAX_ARCHIVE_BYTES:
                raise BackupError('Размер данных превышает предел одной копии: 512 МБ')
            manifest = {'application': APP_NAME, 'app_version': APP_VERSION, 'schema_version': SCHEMA_VERSION,
                'backup_format': 1, 'created_at': datetime.now().isoformat(), 'unavailable_photos': missing,
                'files': {name: file_hash(path) for name, path in files.items()}}
            with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('version.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                archive.writestr('inspection_photos/', '')
                for name, path in files.items():
                    archive.write(path, name)
            with tempfile.TemporaryDirectory(prefix='check-', dir=stage) as check:
                extract_verified(destination, Path(check), allow_incomplete=allow_incomplete)
        return destination
    except Exception as exc:
        destination.unlink(missing_ok=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f'Не удалось создать полную резервную копию: {exc}') from exc


def extract_verified(archive_path, destination, *, allow_incomplete=False):
    from app.services.backup_service import BackupError, verify_sqlite
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) > 10000 or len(set(names)) != len(names) or sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
                raise BackupError('Недопустимый размер или повторяющиеся записи архива')
            if not {'database.db', 'version.json'}.issubset(names):
                raise BackupError('В ZIP отсутствуют database.db или version.json')
            for item in infos:
                name = item.filename
                if (item.external_attr >> 16) & 0o170000 == 0o120000 or item.flag_bits & 1:
                    raise BackupError('Ссылки и зашифрованные записи ZIP не поддерживаются')
                if name == 'inspection_photos/':
                    continue
                if item.is_dir():
                    raise BackupError('Неожиданный каталог внутри архива')
                if name not in ('database.db', 'version.json'):
                    safe_photo_path(destination, name)
                    if Path(name).suffix.lower() not in ('.jpg', '.jpeg', '.png') or '\\' in name:
                        raise BackupError('В архиве есть неподдерживаемый файл')
            if archive.getinfo('version.json').file_size > 2 * 1024 * 1024:
                raise BackupError('Слишком большой файл версии')
            manifest = json.loads(archive.read('version.json'))
            if not isinstance(manifest, dict) or manifest.get('application') != APP_NAME or manifest.get('backup_format') != 1:
                raise BackupError('Это не поддерживаемая копия MagicLab Manager')
            if manifest.get('schema_version') not in (2, 3) or not isinstance(manifest.get('files'), dict):
                raise BackupError('Версия схемы архива не поддерживается')
            if manifest.get('unavailable_photos') and not allow_incomplete:
                raise BackupError('Эта страховочная копия зафиксировала состояние с недоступными фото. Выберите более раннюю полную копию; список файлов есть в version.json.')
            content_names = set(names) - {'version.json', 'inspection_photos/'}
            if set(manifest['files']) != content_names:
                raise BackupError('Состав ZIP не совпадает с описанием копии')
            for name in content_names:
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, path.open('xb') as target:
                    shutil.copyfileobj(source, target)
                if file_hash(path) != manifest['files'][name]:
                    raise BackupError('Контрольная сумма файла в копии не совпадает')
        (destination / 'inspection_photos').mkdir(exist_ok=True)
        db = destination / 'database.db'
        verify_sqlite(db)
        with closing(sqlite3.connect(db)) as connection:
            if connection.execute('PRAGMA user_version').fetchone()[0] != manifest['schema_version']:
                raise BackupError('Версия базы не совпадает с описанием ZIP')
        if not (allow_incomplete and manifest.get('unavailable_photos')):
            check_photos(db, destination)
        return db
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f'Не удалось проверить ZIP-копию: {exc}') from exc


def verify_backup(path):
    from app.services.backup_service import verify_sqlite
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with tempfile.TemporaryDirectory(prefix='magiclab-verify-') as folder:
            extract_verified(path, Path(folder))
    else:
        verify_sqlite(path)


def restore_zip_or_legacy(current_db, backup_file, backup_dir, prepare):
    from app.services.backup_service import BackupError, verify_sqlite
    current_db, backup_file = Path(current_db).resolve(), Path(backup_file).resolve()
    if current_db == backup_file:
        raise BackupError('Выберите резервную копию, а не рабочую базу')
    # Для атомарных переименований восстановление остаётся на том же томе.
    with tempfile.TemporaryDirectory(prefix='.mlr-', dir=current_db.parent) as folder:
        stage = Path(folder)
        if backup_file.suffix.lower() == '.zip':
            staged_db = extract_verified(backup_file, stage)
        else:
            verify_sqlite(backup_file)
            staged_db = stage / 'database.db'
            shutil.copy2(backup_file, staged_db)
            (stage / 'inspection_photos').mkdir()
            # Старый .db без вложений допустим только если в нём нет ссылок на фотографии.
            check_photos(staged_db, stage)
        safety = create_zip(current_db, Path(backup_dir), 'before_restore', allow_incomplete=True)
        try:
            prepare(staged_db)
            verify_sqlite(staged_db)
            check_photos(staged_db, stage)
            current_photos = current_db.parent / 'inspection_photos'
            if current_photos.is_symlink() or current_photos.resolve().parent != current_db.parent:
                raise BackupError('Папка фотографий не должна быть ссылкой на другой каталог')
            previous = stage / 'previous_photos'
            moved_old = moved_new = False
            try:
                if current_photos.exists():
                    os.replace(current_photos, previous)
                    moved_old = True
                os.replace(stage / 'inspection_photos', current_photos)
                moved_new = True
                os.replace(staged_db, current_db)
            except Exception:
                if moved_new:
                    os.replace(current_photos, stage / 'failed_photos')
                if moved_old:
                    os.replace(previous, current_photos)
                raise
            return current_db, safety
        except Exception as exc:
            raise BackupError(f'Восстановление не выполнено. Страховочная ZIP-копия: {safety}. {exc}') from exc
