from datetime import datetime
from pathlib import Path
import json
import sqlite3
import zipfile

import pytest
from PySide6.QtCore import Qt, QPointF, QUrl
from PySide6.QtGui import QImage, QColor, QTextDocument
from PySide6.QtTest import QTest, QSignalSpy
from sqlalchemy import select

from app.database import Database
from app.models import Customer, Vehicle, CarClass, UserRole, Order, DamageMark, InspectionPhoto, VehicleInspection, AuditLog
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.services.order_service import OrderService
from app.services.inspection_service import InspectionService, safe_photo_path, load_photo
from app.services.access_service import AccessDenied
from app.services.backup_service import create_backup, restore_backup, BackupError, verify_sqlite
from app.services.backup_archive import verify_backup

MARK = dict(view='LEFT', normalized_x=0.56, normalized_y=0.55, body_element='LEFT_FRONT_DOOR',
            damage_type='LIGHT_SCRATCH', severity='MINOR', comment='Не полировать без согласования', paint_thickness_um=115)


@pytest.fixture
def inspection_db(tmp_path):
    path = tmp_path / 'data/magiclab.db'
    path.parent.mkdir()
    db = Database(f'sqlite:///{path.as_posix()}')
    db.create_schema()
    db.seed_demo_services()
    with db.session() as session:
        owner = AuthService(session).create_admin('owner', 'password', 'Руководитель')
        session.commit()
        db.sign_in(owner)
    with db.session() as session:
        users = UserService(session)
        master = users.create('master', 'password', 'Мастер', UserRole.MASTER)
        admin = users.create('admin', 'password', 'Администратор', UserRole.ADMIN)
        customer = Customer(full_name='Учебный клиент', phone='+7 (900) 000-00-00')
        vehicle = Vehicle(customer=customer, brand='Toyota', model='Camry', license_plate='А000АА125', car_class=CarClass.SEDAN)
        session.add_all([customer, vehicle])
        session.flush()
        order = OrderService(session).create_order(customer, vehicle, datetime(2026, 9, 4, 10), [1], assigned_master_id=master.id)
        other = OrderService(session).create_order(customer, vehicle, datetime(2026, 9, 5, 10), [1])
        session.commit()
    yield db, order.id, other.id, owner, admin, master
    db.dispose()


@pytest.fixture
def sample_photo(tmp_path):
    path = tmp_path / 'source.png'
    image = QImage(200, 120, QImage.Format.Format_RGB32)
    image.fill(QColor('#818990'))
    assert image.save(str(path))
    return path


def test_create_one_inspection_and_order_link(inspection_db):
    db, order_id, other, *_ = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        identifier = service.create(order_id)
        assert service.create(order_id) == identifier
        session.commit()
        assert session.get(VehicleInspection, identifier).order_id == order_id
        assert service.get(other)['inspection'] is None
        assert session.scalar(select(AuditLog).where(AuditLog.action == 'Создание осмотра'))


@pytest.mark.parametrize('coordinate', [0.0, 0.5, 1.0])
def test_normalized_coordinates(coordinate):
    assert InspectionService.validate_mark({**MARK, 'normalized_x': coordinate})['normalized_x'] == coordinate


@pytest.mark.parametrize('coordinate', [-0.01, 1.01, float('nan'), float('inf'), None, 'wrong'])
def test_invalid_coordinates(coordinate):
    with pytest.raises(ValueError, match='Координаты'):
        InspectionService.validate_mark({**MARK, 'normalized_y': coordinate})


def test_create_edit_delete_mark_and_audit(inspection_db):
    db, order_id, *_ = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        identifier = service.save_mark(order_id, MARK)
        service.save_mark(order_id, {**MARK, 'comment': 'Уточнено', 'severity': 'MAJOR'}, identifier)
        session.commit()
        data = service.get(order_id)['inspection']['marks'][0]
        assert data['comment'] == 'Уточнено' and data['severity'] == 'MAJOR'
        service.delete_mark(order_id, identifier)
        session.commit()
        assert not service.get(order_id)['inspection']['marks']
        actions = set(session.scalars(select(AuditLog.action)))
        assert {'Добавление замечания', 'Изменение замечания', 'Удаление замечания'} <= actions


def test_foreign_mark_rejected(inspection_db):
    db, order_id, other, *_ = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        identifier = service.save_mark(order_id, MARK)
        with pytest.raises(ValueError, match='принадлежит'):
            service.save_mark(other, MARK, identifier)
        session.rollback()


def test_photo_copied_and_not_dependent_on_source(inspection_db, sample_photo):
    db, order_id, *_ = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        mark_id = service.save_mark(order_id, MARK)
        photo_id = service.add_photo(order_id, sample_photo, 'Учебный снимок', mark_id)
        session.commit()
        path = service.photo_path(order_id, photo_id)
        assert path != sample_photo and path.read_bytes() == sample_photo.read_bytes()
        assert path.parent.name == session.get(Order, order_id).public_number
        assert session.get(InspectionPhoto, photo_id).damage_mark_id == mark_id
        sample_photo.unlink()
        assert not load_photo(path).isNull()


def test_missing_and_corrupt_photo(inspection_db, sample_photo):
    db, order_id, *_ = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        identifier = service.add_photo(order_id, sample_photo)
        session.commit()
        path = service.photo_path(order_id, identifier)
        path.write_bytes(b'corrupt')
        with pytest.raises(ValueError, match='повреждена'):
            load_photo(path)
        path.unlink()
        with pytest.raises(ValueError, match='не найдена'):
            load_photo(path)


def test_photo_rollback_and_delete_mark_removes_file(inspection_db, sample_photo):
    db, order_id, *_ = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        identifier = service.add_photo(order_id, sample_photo)
        path = service.photo_path(order_id, identifier)
        session.rollback()
        assert not path.exists()
        mark_id = service.save_mark(order_id, MARK)
        photo_id = service.add_photo(order_id, sample_photo, damage_mark_id=mark_id)
        session.commit()
        path = service.photo_path(order_id, photo_id)
        service.delete_mark(order_id, mark_id)
        session.commit()
        assert not path.exists() and session.get(InspectionPhoto, photo_id) is None


def test_admin_access_master_readonly_and_review_invalidation(inspection_db, sample_photo):
    db, order_id, other, owner, admin, master = inspection_db
    db.sign_in(admin)
    with db.session() as session:
        service = InspectionService(session)
        mark_id = service.save_mark(order_id, MARK)
        photo_id = service.add_photo(order_id, sample_photo, damage_mark_id=mark_id)
        service.save_details(order_id, 'Есть замечания', 'Согласовать полировку', True)
        session.commit()
    db.sign_in(master)
    with db.session() as session:
        service = InspectionService(session)
        assert service.get(order_id)['inspection']['marks']
        assert service.photo_path(order_id, photo_id).exists()
        for operation in (lambda: service.save_mark(order_id, MARK), lambda: service.delete_mark(order_id, mark_id),
            lambda: service.add_photo(order_id, sample_photo), lambda: service.delete_photo(order_id, photo_id),
            lambda: service.save_details(order_id, '', ''), lambda: service.get(other), lambda: service.acknowledge_master(other)):
            with pytest.raises(AccessDenied):
                operation()
        service.acknowledge_master(order_id)
        session.commit()
        assert service.get(order_id)['inspection']['master_reviewed_by_user_id'] == master.id
    db.sign_in(owner)
    with db.session() as session:
        service = InspectionService(session)
        service.save_mark(order_id, {**MARK, 'comment': 'Обновлённый дефект'}, mark_id)
        session.commit()
        data = service.get(order_id)['inspection']
        assert not data['master_reviewed'] and not data['customer_acknowledged']


def test_photos_in_zip_and_restore(inspection_db, sample_photo, tmp_path):
    db, order_id, *_ = inspection_db
    current = Path(db.engine.url.database)
    with db.session() as session:
        service = InspectionService(session)
        photo_id = service.add_photo(order_id, sample_photo, 'Архивное фото')
        session.commit()
        path = service.photo_path(order_id, photo_id)
        original = path.read_bytes()
        archive = create_backup(current, tmp_path / 'copies', session=session)
        session.commit()
    with zipfile.ZipFile(archive) as bundle:
        assert {'database.db', 'version.json', 'inspection_photos/'} <= set(bundle.namelist())
        assert bundle.read(path.relative_to(current.parent).as_posix()) == original
        assert json.loads(bundle.read('version.json'))['schema_version'] == 3
    verify_backup(archive)
    with db.session() as session:
        InspectionService(session).delete_photo(order_id, photo_id)
        session.commit()
        assert not path.exists()
        restored, safety = restore_backup(current, archive, tmp_path / 'copies', session=session)
    assert restored == current.resolve() and safety.suffix == '.zip'
    assert path.read_bytes() == original
    verify_backup(safety)
    assert db.actor_id is None


@pytest.mark.parametrize('entry', ['../outside.jpg', '/absolute.png', 'inspection_photos/../../escape.png', 'inspection_photos/x/a.exe'])
def test_unsafe_zip_rejected(tmp_path, entry):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('database.db', b'wrong')
        bundle.writestr('version.json', '{}')
        bundle.writestr(entry, b'wrong')
    with pytest.raises(BackupError):
        verify_backup(archive)
    assert not (tmp_path / 'outside.jpg').exists()


def test_canvas_resize_and_selection(qt_app):
    from app.ui.inspection_canvas import InspectionCanvas
    canvas = InspectionCanvas()
    canvas.set_view('LEFT', [{**MARK, 'id': 7}])
    canvas.resize(480, 300)
    canvas.show()
    qt_app.processEvents()
    position = canvas.markers[7].pos()
    canvas.resize(880, 550)
    qt_app.processEvents()
    assert canvas.markers[7].pos() == position == QPointF(448, 242)
    spy = QSignalSpy(canvas.marker_clicked)
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(position))
    assert spy.count() == 1 and spy.at(0)[0] == 7
    canvas.close()


def test_inspection_tabs_master_ui_and_document(qt_app, inspection_db, sample_photo):
    from app.ui.dialogs.order_dialogs import OrderDetailsDialog, write_pdf
    from app.ui.pages.master_page import MasterOrderDialog
    db, order_id, _, owner, _, master = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        service.save_mark(order_id, MARK)
        service.add_photo(order_id, sample_photo, 'Тестовое изображение')
        session.commit()
    dialog = OrderDetailsDialog(db, order_id)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    qt_app.processEvents()
    assert dialog.tabs.tabText(1) == 'Осмотр ЛКП'
    assert dialog.inspection_panel.save_button.isVisible()
    document = dialog._document()
    assert 'Карта первичного осмотра ЛКП' in document.toPlainText()
    assert 'Фотоприложение' in document.toPlainText()
    assert not document.resource(QTextDocument.ResourceType.ImageResource, QUrl('inspection://scheme/LEFT')).isNull()
    pdf = sample_photo.parent / 'inspection.pdf'
    write_pdf(document, str(pdf))
    assert pdf.stat().st_size > 1000
    dialog.close()
    db.sign_in(master)
    dialog = MasterOrderDialog(db, order_id)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    qt_app.processEvents()
    panel = dialog.inspection_panel
    assert not panel.save_button.isVisible() and not panel.delete_button.isVisible() and not panel.print_button.isVisible()
    assert not panel.canvas.editable and panel.review_button.isVisible()
    panel.review_button.click()
    assert not panel.review_button.isEnabled()
    dialog.close()


def test_restore_missing_photo_uses_safety_inventory(inspection_db, sample_photo, tmp_path):
    db, order_id, *_ = inspection_db
    current = Path(db.engine.url.database)
    with db.session() as session:
        service = InspectionService(session)
        photo_id = service.add_photo(order_id, sample_photo)
        session.commit()
        path = service.photo_path(order_id, photo_id)
        archive = create_backup(current, tmp_path / 'copies', session=session)
        session.commit()
        path.unlink()
        with pytest.raises(BackupError, match='фото'):
            create_backup(current, tmp_path / 'copies', session=session)
        _, safety = restore_backup(current, archive, tmp_path / 'copies', session=session)
    assert path.is_file()
    with zipfile.ZipFile(safety) as bundle:
        assert json.loads(bundle.read('version.json'))['unavailable_photos']


def test_restore_replace_failure_rolls_back_photos(inspection_db, sample_photo, tmp_path, monkeypatch):
    import app.services.backup_archive as module
    db, order_id, *_ = inspection_db
    current = Path(db.engine.url.database)
    with db.session() as session:
        service = InspectionService(session)
        photo_id = service.add_photo(order_id, sample_photo)
        session.commit()
        path = service.photo_path(order_id, photo_id)
        original = path.read_bytes()
        archive = create_backup(current, tmp_path / 'copies', session=session)
        session.commit()
    replace = module.os.replace
    def fail_database(source, destination):
        if Path(source).name == 'database.db':
            raise PermissionError('simulated database replacement failure')
        return replace(source, destination)
    monkeypatch.setattr(module.os, 'replace', fail_database)
    with db.session() as session:
        with pytest.raises(BackupError):
            restore_backup(current, archive, tmp_path / 'copies', session=session)
    assert path.read_bytes() == original
    verify_sqlite(current)
    assert list((tmp_path / 'copies').glob('before_restore_*.zip'))


def test_photo_caption_and_rebinding(inspection_db, sample_photo):
    db, order_id, other, *_ = inspection_db
    with db.session() as session:
        service = InspectionService(session)
        mark = service.save_mark(order_id, MARK)
        photo = service.add_photo(order_id, sample_photo)
        service.update_photo(order_id, photo, 'Новая подпись', mark)
        session.commit()
        data = service.get(order_id)['inspection']['photos'][0]
        assert data['caption'] == 'Новая подпись' and data['damage_mark_id'] == mark
        with pytest.raises(AccessDenied):
            service.photo_path(other, photo)


def test_reassignment_invalidates_review(inspection_db):
    db, order_id, _, owner, _, master = inspection_db
    with db.session() as session:
        InspectionService(session).create(order_id)
        session.commit()
    db.sign_in(master)
    with db.session() as session:
        InspectionService(session).acknowledge_master(order_id)
        session.commit()
    db.sign_in(owner)
    with db.session() as session:
        order = session.get(Order, order_id)
        OrderService(session).update_order(order, order.scheduled_at, [item.service_id for item in order.items],
                                           order.prepayment, order.comment, assigned_master_id=None)
        session.commit()
        assert not InspectionService(session).get(order_id)['inspection']['master_reviewed']


def test_schema_two_migration_keeps_orders(inspection_db):
    db, order_id, *_ = inspection_db
    with db.engine.begin() as connection:
        connection.exec_driver_sql('DROP TABLE inspection_photos')
        connection.exec_driver_sql('DROP TABLE damage_marks')
        connection.exec_driver_sql('DROP TABLE vehicle_inspections')
        connection.exec_driver_sql('PRAGMA user_version=2')
    db.create_schema()
    assert db.migration_backup.name.startswith('before_inspection_')
    with db.session() as session:
        assert session.get(Order, order_id)
        assert InspectionService(session).get(order_id)['inspection'] is None
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA user_version').scalar_one() == 3


def test_close_warns_and_selection_switches_view(qt_app, inspection_db, monkeypatch):
    from app.ui.dialogs.order_dialogs import OrderDetailsDialog
    from PySide6.QtWidgets import QMessageBox
    db, order_id, *_ = inspection_db
    with db.session() as session:
        InspectionService(session).save_mark(order_id, MARK)
        session.commit()
    dialog = OrderDetailsDialog(db, order_id)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    panel = dialog.inspection_panel
    panel.table.selectRow(0)
    assert panel.view == 'LEFT' and panel.selected_id == panel.marks[0]['id']
    panel.comment.setPlainText('Не потерять при закрытии')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Cancel)
    dialog.close()
    assert dialog.isVisible()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Save)
    dialog.close()
    assert not dialog.isVisible()
    with db.session() as session:
        assert InspectionService(session).get(order_id)['inspection']['general_comment'] == 'Не потерять при закрытии'
