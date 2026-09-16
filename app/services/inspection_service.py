"""Осмотр, проверка прав и управляемые копии фотографий. Без зависимости от виджетов."""
from __future__ import annotations

import logging
import math
import re
import shutil
from pathlib import Path
from uuid import uuid4

from PySide6.QtGui import QImageReader
from sqlalchemy import event, select

from app.config import DATA_DIR
from app.inspection_catalog import VIEWS, BODY_ELEMENTS, DAMAGE_TYPES, SEVERITIES
from app.inspection_geometry import place_mark
from app.models import Order, Vehicle, VehicleInspection, DamageMark, InspectionPhoto, User, UserRole, now_local
from app.services.access_service import require, AccessDenied
from app.services.audit_service import record


def data_directory(session) -> Path:
    location = session.get_bind().url.database
    return Path(location).resolve().parent if location and location != ':memory:' else DATA_DIR


def safe_photo_path(data_dir: Path, relative: str) -> Path:
    """Не доверяем пути из SQLite: запрещены абсолютные пути, выход из каталога и ссылки."""
    parts = relative.replace('\\', '/').split('/')
    if len(parts) != 3 or parts[0] != 'inspection_photos' or any(p in ('', '.', '..') or ':' in p for p in parts):
        raise ValueError('Некорректный путь фотографии в базе')
    photo_dir = data_dir / 'inspection_photos'
    if photo_dir.is_symlink():
        raise ValueError('Папка фотографий не должна быть ссылкой')
    root = photo_dir.resolve()
    if root != data_dir.resolve() / 'inspection_photos':
        raise ValueError('Папка фотографий не должна перенаправляться в другой каталог')
    path = data_dir.joinpath(*parts)
    if not path.resolve().is_relative_to(root) or path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Фотография находится за пределами папки приложения')
    return path


def load_photo(path: Path):
    if not path.is_file():
        raise ValueError('Фотография не найдена. Восстановите файл из полной резервной копии.')
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError('Размер фотографии превышает 30 МБ')
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if not reader.canRead() or reader.format().data().lower() not in (b'jpeg', b'jpg', b'png'):
        raise ValueError('Фотография повреждена или имеет неподдерживаемый формат')
    if size.width() * size.height() > 40_000_000:
        raise ValueError('Фотография слишком большая: допускается до 40 мегапикселей')
    image = reader.read()
    if image.isNull():
        raise ValueError('Не удалось прочитать фотографию: файл повреждён')
    return image


def _file_transaction(session):
    if 'inspection_files' in session.info:
        return session.info['inspection_files']
    pending = {'new': set(), 'deleted': set()}
    session.info['inspection_files'] = pending

    def cleanup(committed):
        for path in pending['deleted' if committed else 'new']:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).exception('Не удалось убрать файл осмотра %s', path)
        pending['new'].clear()
        pending['deleted'].clear()
    event.listen(session, 'after_commit', lambda _session: cleanup(True))
    event.listen(session, 'after_rollback', lambda _session: cleanup(False))
    return pending


class InspectionService:
    def __init__(self, session):
        self.session = session
        self.data_dir = data_directory(session)

    def _order(self, order_id, edit=False):
        actor = require(self.session, 'inspection_edit' if edit else 'inspection_view')
        # Мастеру не возвращается ORM-заказ с финансовыми полями и контактами.
        row = self.session.execute(select(Order.id, Order.public_number, Order.assigned_master_id,
            Vehicle.brand, Vehicle.model, Vehicle.license_plate).join(Vehicle, Order.vehicle_id == Vehicle.id)
            .where(Order.id == order_id)).mappings().first()
        if not row or (actor.role == UserRole.MASTER and row['assigned_master_id'] != actor.id):
            raise AccessDenied('Карта осмотра этого заказа недоступна')
        return row, actor

    def _inspection(self, order_id, edit=False, create=False):
        order, actor = self._order(order_id, edit)
        inspection = self.session.scalar(select(VehicleInspection).where(VehicleInspection.order_id == order_id))
        if not inspection and create:
            require(self.session, 'inspection_edit')
            inspection = VehicleInspection(order_id=order_id, created_by_user_id=actor.id)
            self.session.add(inspection)
            self.session.flush()
            record(self.session, 'Создание осмотра', 'Создана карта первичного осмотра ЛКП', order['public_number'])
        return inspection, order, actor

    def create(self, order_id):
        inspection, _, _ = self._inspection(order_id, edit=True, create=True)
        return inspection.id

    def get(self, order_id):
        inspection, order, _ = self._inspection(order_id)
        result = {'order_id': order_id, 'number': order['public_number'],
                  'vehicle': f"{order['brand']} {order['model']} · {order['license_plate']}", 'inspection': None}
        if not inspection:
            return result
        fields = ('id', 'general_condition', 'general_comment', 'created_at', 'updated_at', 'created_by_user_id',
                  'customer_acknowledged', 'customer_acknowledged_at', 'master_reviewed',
                  'master_reviewed_by_user_id', 'master_reviewed_at')
        value = {field: getattr(inspection, field) for field in fields}
        value['marks'] = [{field: getattr(mark, field) for field in ('id', 'view', 'normalized_x', 'normalized_y',
            'body_element', 'damage_type', 'severity', 'comment', 'paint_thickness_um')}
            for mark in self.session.scalars(select(DamageMark).where(DamageMark.inspection_id == inspection.id).order_by(DamageMark.id))]
        value['photos'] = [{field: getattr(photo, field) for field in ('id', 'damage_mark_id', 'file_path',
            'original_filename', 'caption', 'created_at')}
            for photo in self.session.scalars(select(InspectionPhoto).where(InspectionPhoto.inspection_id == inspection.id).order_by(InspectionPhoto.id))]
        reviewer = self.session.get(User, inspection.master_reviewed_by_user_id) if inspection.master_reviewed_by_user_id else None
        value['reviewer_name'] = reviewer.full_name if reviewer else ''
        result['inspection'] = value
        return result

    @staticmethod
    def _invalidate(inspection):
        inspection.updated_at = now_local()
        inspection.master_reviewed = inspection.customer_acknowledged = False
        inspection.master_reviewed_at = inspection.master_reviewed_by_user_id = None
        inspection.customer_acknowledged_at = None

    def save_details(self, order_id, general_condition, general_comment, customer_acknowledged=False):
        inspection, order, _ = self._inspection(order_id, edit=True, create=True)
        condition, comment = general_condition.strip(), general_comment.strip()
        if len(condition) > 180 or len(comment) > 5000:
            raise ValueError('Состояние — до 180 символов, общий комментарий — до 5000')
        changed = (inspection.general_condition, inspection.general_comment) != (condition, comment)
        old = f'{inspection.general_condition}; {inspection.general_comment}'
        if changed:
            self._invalidate(inspection)
        if changed or inspection.customer_acknowledged != bool(customer_acknowledged):
            inspection.general_condition, inspection.general_comment = condition, comment
            inspection.customer_acknowledged = bool(customer_acknowledged)
            inspection.customer_acknowledged_at = now_local() if customer_acknowledged else None
            record(self.session, 'Изменение осмотра', f'Было: {old[:650]}. Стало: {condition}; {comment[:650]}. '
                f'Отметка клиента: {"да" if customer_acknowledged else "нет"}', order['public_number'])
        self.session.flush()
        return inspection.id

    @staticmethod
    def validate_mark(values):
        values = dict(values)
        for field, catalog in (('view', VIEWS), ('body_element', BODY_ELEMENTS), ('damage_type', DAMAGE_TYPES), ('severity', SEVERITIES)):
            if values.get(field) not in catalog:
                raise ValueError('Выберите вид, элемент кузова, дефект и степень из справочника')
        for field in ('normalized_x', 'normalized_y'):
            try:
                value = float(values[field])
            except (KeyError, TypeError, ValueError):
                raise ValueError('Координаты должны быть числами от 0 до 1') from None
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('Координаты должны находиться в диапазоне от 0 до 1')
            values[field] = value
        thickness = values.get('paint_thickness_um')
        if thickness is not None and (isinstance(thickness, bool) or not isinstance(thickness, int) or not 0 <= thickness <= 5000):
            raise ValueError('Толщина ЛКП должна быть целым числом от 0 до 5000 мкм')
        comment = str(values.get('comment', '')).strip()
        if len(comment) > 5000:
            raise ValueError('Комментарий к дефекту — до 5000 символов')
        return {**{key: values[key] for key in ('view', 'normalized_x', 'normalized_y', 'body_element', 'damage_type', 'severity')},
                'comment': comment, 'paint_thickness_um': thickness}

    def save_mark(self, order_id, values, mark_id=None):
        inspection, order, _ = self._inspection(order_id, edit=True, create=True)
        values = place_mark(self.validate_mark(values))
        mark = self.session.get(DamageMark, mark_id) if mark_id else DamageMark(inspection_id=inspection.id)
        if not mark or mark.inspection_id != inspection.id:
            raise ValueError('Замечание не принадлежит этому осмотру')
        before = f'{mark.view} ({mark.normalized_x}, {mark.normalized_y}); {BODY_ELEMENTS.get(mark.body_element, "")}; {DAMAGE_TYPES.get(mark.damage_type, "")}; {mark.comment or ""}' if mark_id else ''
        for key, value in values.items():
            setattr(mark, key, value)
        self.session.add(mark)
        self._invalidate(inspection)
        self.session.flush()
        record(self.session, 'Изменение замечания' if mark_id else 'Добавление замечания',
               f'ID {mark.id}. Было: {before[:500]}. {BODY_ELEMENTS[mark.body_element]}; {DAMAGE_TYPES[mark.damage_type]}; '
               f'{SEVERITIES[mark.severity]}; {mark.view} ({mark.normalized_x}, {mark.normalized_y}); ЛКП: {mark.paint_thickness_um}; {mark.comment[:700]}', order['public_number'])
        return mark.id

    def delete_mark(self, order_id, mark_id):
        inspection, order, _ = self._inspection(order_id, edit=True)
        mark = self.session.get(DamageMark, mark_id)
        if not inspection or not mark or mark.inspection_id != inspection.id:
            raise ValueError('Замечание не принадлежит этому осмотру')
        for photo in list(self.session.scalars(select(InspectionPhoto).where(InspectionPhoto.damage_mark_id == mark_id))):
            self._remove_photo(photo)
        # Фото удаляем до родительского маркера: иначе CASCADE опередит ORM DELETE.
        self.session.flush()
        record(self.session, 'Удаление замечания', f'ID {mark.id}: {BODY_ELEMENTS[mark.body_element]}, {DAMAGE_TYPES[mark.damage_type]}; вместе с привязанными фото', order['public_number'])
        self.session.delete(mark)
        self._invalidate(inspection)
        self.session.flush()

    def add_photo(self, order_id, source, caption='', damage_mark_id=None):
        inspection, order, _ = self._inspection(order_id, edit=True, create=True)
        source = Path(source)
        if source.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
            raise ValueError('Выберите фотографию JPG, JPEG или PNG')
        if len(caption) > 1000:
            raise ValueError('Подпись фотографии — до 1000 символов')
        if damage_mark_id is not None:
            mark = self.session.get(DamageMark, damage_mark_id)
            if not mark or mark.inspection_id != inspection.id:
                raise ValueError('Фотография и замечание должны принадлежать одному осмотру')
        load_photo(source)
        folder = re.sub(r'[^A-Za-z0-9_-]', '_', order['public_number'])
        relative = f'inspection_photos/{folder}/{uuid4().hex}{source.suffix.lower()}'
        destination = safe_photo_path(self.data_dir, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = _file_transaction(self.session)
        pending['new'].add(destination)
        shutil.copy2(source, destination)
        load_photo(destination)
        photo = InspectionPhoto(inspection_id=inspection.id, damage_mark_id=damage_mark_id, file_path=relative,
                                original_filename=source.name[:255], caption=caption.strip())
        self.session.add(photo)
        self._invalidate(inspection)
        self.session.flush()
        record(self.session, 'Добавление фото осмотра', f'Фото ID {photo.id}; замечание {damage_mark_id or "общее"}; {caption[:700]}', order['public_number'])
        return photo.id

    def photo_path(self, order_id, photo_id):
        inspection, _, _ = self._inspection(order_id)
        photo = self.session.get(InspectionPhoto, photo_id)
        if not inspection or not photo or photo.inspection_id != inspection.id:
            raise AccessDenied('Фотография этого заказа недоступна')
        return safe_photo_path(self.data_dir, photo.file_path)

    def _remove_photo(self, photo):
        _file_transaction(self.session)['deleted'].add(safe_photo_path(self.data_dir, photo.file_path))
        self.session.delete(photo)

    def delete_photo(self, order_id, photo_id):
        inspection, order, _ = self._inspection(order_id, edit=True)
        self.photo_path(order_id, photo_id)
        photo = self.session.get(InspectionPhoto, photo_id)
        record(self.session, 'Удаление фото осмотра', f'Фото ID {photo.id}: {photo.caption[:700]}', order['public_number'])
        self._remove_photo(photo)
        self._invalidate(inspection)
        self.session.flush()

    def update_photo(self, order_id, photo_id, caption, damage_mark_id=None):
        inspection, order, _ = self._inspection(order_id, edit=True)
        self.photo_path(order_id, photo_id)
        if len(caption) > 1000:
            raise ValueError('Подпись фотографии — до 1000 символов')
        if damage_mark_id is not None:
            mark = self.session.get(DamageMark, damage_mark_id)
            if not mark or mark.inspection_id != inspection.id:
                raise ValueError('Замечание не принадлежит этому осмотру')
        photo = self.session.get(InspectionPhoto, photo_id)
        before = f'замечание {photo.damage_mark_id}; {photo.caption}'
        photo.caption, photo.damage_mark_id = caption.strip(), damage_mark_id
        self._invalidate(inspection)
        record(self.session, 'Изменение фото осмотра', f'Фото ID {photo.id}. Было: {before[:750]}. '
               f'Стало: замечание {damage_mark_id}; {caption[:750]}', order['public_number'])
        self.session.flush()

    def acknowledge_master(self, order_id):
        inspection, order, actor = self._inspection(order_id)
        if actor.role != UserRole.MASTER or order['assigned_master_id'] != actor.id:
            raise AccessDenied('Ознакомление отмечает только назначенный мастер под своей учётной записью')
        if not inspection:
            raise ValueError('Администратор ещё не создал карту осмотра')
        inspection.master_reviewed = True
        inspection.master_reviewed_by_user_id = actor.id
        inspection.master_reviewed_at = now_local()
        record(self.session, 'Ознакомление с осмотром', 'Назначенный мастер отметил ознакомление с текущей картой ЛКП', order['public_number'])
        self.session.flush()
