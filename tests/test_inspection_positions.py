"""Регрессии: области кузова, старые отметки, GC во вложенных диалогах и отступы."""
import gc

import pytest
from PySide6.QtCore import QPoint, QPointF, QTimer, Qt
from PySide6.QtWidgets import QDialog, QFileDialog
from PySide6.QtTest import QSignalSpy, QTest

from app.inspection_catalog import BODY_ELEMENTS
from app.inspection_geometry import REGIONS, WIDTH, HEIGHT, element_at, place_mark, position_matches, project_marks
from app.models import DamageMark
from app.services.inspection_service import InspectionService
from app.ui.inspection_canvas import InspectionCanvas, render_scheme
from app.ui.dialogs.inspection_dialogs import DamageDialog
from tests.test_inspection import inspection_db, sample_photo, MARK


@pytest.mark.parametrize('view,region', [(view, region) for view, regions in REGIONS.items() for region in regions])
def test_svg_regions_and_mirrored_sides(view, region):
    x, y = region.anchor[0]/WIDTH, region.anchor[1]/HEIGHT
    assert element_at(view, x, y) == region.element
    assert position_matches(view, region.element, x, y)


@pytest.mark.parametrize('element', BODY_ELEMENTS)
def test_every_body_element_has_a_valid_position(element):
    mark = place_mark({**MARK, 'body_element': element, 'normalized_x': .01, 'normalized_y': .01})
    assert position_matches(mark['view'], element, mark['normalized_x'], mark['normalized_y'])


def test_roof_and_hood_cannot_stay_on_rear_bumper():
    for element in ('ROOF', 'HOOD'):
        mark = place_mark({**MARK, 'view': 'REAR', 'body_element': element,
                           'normalized_x': .5, 'normalized_y': .69})
        assert mark['view'] == 'TOP'
        assert position_matches(mark['view'], element, mark['normalized_x'], mark['normalized_y'])


def test_valid_precise_point_is_not_snapped_to_center():
    assert place_mark(MARK) == MARK


def test_save_normalizes_new_position_but_read_keeps_legacy_db(inspection_db):
    db, order_id, *_ = inspection_db
    wrong = {**MARK, 'view': 'REAR', 'body_element': 'ROOF', 'normalized_x': .5, 'normalized_y': .69}
    with db.session() as session:
        service = InspectionService(session)
        identifier = service.save_mark(order_id, wrong)
        session.commit()
        mark = session.get(DamageMark, identifier)
        assert mark.view == 'TOP'
        # Воспроизводим запись старой версии: чтение/отрисовка не меняют доказательные данные.
        mark.view, mark.normalized_x, mark.normalized_y = 'REAR', .5, .69
        session.commit()
        original = service.get(order_id)['inspection']['marks']
        displayed = project_marks(original)
        assert original[0]['view'] == 'REAR'
        assert displayed[0]['view'] == 'TOP' and displayed[0]['position_adjusted']
    with db.session() as session:
        stored = session.get(DamageMark, identifier)
        assert (stored.view, stored.normalized_x, stored.normalized_y) == ('REAR', .5, .69)


def test_canvas_ignores_blank_background_and_identifies_clicked_door(qt_app):
    canvas = InspectionCanvas()
    canvas.editable = True
    canvas.set_view('LEFT', [])
    canvas.resize(600, 380)
    canvas.show()
    qt_app.processEvents()
    spy = QSignalSpy(canvas.point_clicked)
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(40, 40)))
    assert spy.count() == 0
    QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=canvas.mapFromScene(QPointF(448, 242)))
    assert spy.count() == 1
    assert element_at('LEFT', *spy.at(0)) == 'LEFT_FRONT_DOOR'
    canvas.close()


def test_damage_dialog_rebinds_body_and_keeps_user_precision(qt_app):
    dialog = DamageDialog({**MARK, 'view': 'REAR', 'body_element': 'REAR_BUMPER',
                           'normalized_x': .5, 'normalized_y': .7})
    dialog.body.setCurrentIndex(dialog.body.findData('ROOF'))
    assert dialog.values['view'] == 'TOP'
    assert dialog.preview.current_view == 'TOP'
    dialog.move_point(.45, .5)
    assert dialog.values['normalized_x'] == .45
    dialog.move_point(.70, .5)  # Капот не является крышей.
    assert dialog.values['normalized_x'] == .45
    assert 'Крыша' in dialog.error.text()
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values['body_element'] == 'ROOF'
    assert dialog.values['normalized_x'] == .45
    dialog.close()


def test_svg_survives_gc_and_nested_photo_dialog(qt_app, sample_photo, monkeypatch):
    canvas = InspectionCanvas()
    canvas.resize(650, 420)
    canvas.show()
    qt_app.processEvents()
    before = canvas.grab().toImage()
    results, errors = [], []
    dialog = DamageDialog(MARK, True, canvas)

    def pick_photos(*_args, **_kwargs):
        # Настоящий вложенный цикл событий, как при открытии диалога выбора файла.
        child = QDialog(dialog)
        def inside():
            try:
                gc.collect()
                qt_app.processEvents()
                results.append(len(canvas.scene().items()))
                assert canvas.scene().schematic.renderer().isValid()
                assert len(dialog.preview.scene().items()) == 3  # SVG, маркер, номер.
                assert canvas.grab().toImage() == before
            except Exception as exc:
                errors.append(exc)
            finally:
                child.reject()
        QTimer.singleShot(0, inside)
        child.exec()
        return [str(sample_photo)], ''

    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', pick_photos)
    def attach():
        try:
            dialog.select_photos()
        except Exception as exc:
            errors.append(exc)
        finally:
            dialog.reject()
    QTimer.singleShot(0, attach)
    dialog.exec()
    assert not errors, errors
    assert results == [1]
    assert dialog.photo_files == [str(sample_photo)]
    gc.collect()
    assert len(canvas.scene().items()) == 1
    assert not render_scheme('TOP', []).isNull()
    canvas.close()


@pytest.mark.parametrize('width,height', [(1286, 678), (1840, 990)])
def test_panel_has_gutter_and_new_mark_uses_clicked_element(qt_app, inspection_db, monkeypatch, width, height):
    from app.ui.dialogs.order_dialogs import OrderDetailsDialog
    db, order_id, *_ = inspection_db
    dialog = OrderDetailsDialog(db, order_id)
    dialog.resize(width, height)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    qt_app.processEvents()
    panel = dialog.inspection_panel
    assert (dialog.width(), dialog.height()) == (width, height)
    assert panel.comment.height() == 52
    canvas_edge = panel.canvas.mapTo(panel, QPoint(panel.canvas.width(), 0)).x()
    table_edge = panel.table.mapTo(panel, QPoint(0, 0)).x()
    assert table_edge - canvas_edge >= 16
    received = []
    monkeypatch.setattr(panel, '_mark_dialog', lambda values: received.append(values))
    panel.change_view('TOP')
    panel.add_mark(.45, .5)
    assert received[0]['body_element'] == 'ROOF'
    panel.add_mark(.01, .01)
    assert len(received) == 1
    dialog.close()


def test_new_mark_photo_and_legacy_refinement_through_real_dialog(qt_app, inspection_db, sample_photo, monkeypatch):
    from app.ui.dialogs.order_dialogs import OrderDetailsDialog
    from app.ui.inspection_print import inspection_print_parts
    db, order_id, *_ = inspection_db
    dialog = OrderDetailsDialog(db, order_id)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    qt_app.processEvents()
    panel = dialog.inspection_panel
    errors = []
    monkeypatch.setattr(QFileDialog, 'getOpenFileNames', lambda *_args, **_kwargs: ([str(sample_photo)], ''))

    def fill_damage():
        active = qt_app.activeModalWidget()
        try:
            assert isinstance(active, DamageDialog)
            active.body.setCurrentIndex(active.body.findData('ROOF'))
            active.move_point(.44, .48)
            active.select_photos()
            gc.collect()
            assert panel.canvas.scene().schematic.renderer().isValid()
            active.save()
            assert active.result() == QDialog.DialogCode.Accepted
        except Exception as exc:
            errors.append(exc)
            if active:
                active.reject()

    QTimer.singleShot(0, fill_damage)
    panel.change_view('REAR')
    panel.add_mark(.5, .7)
    assert not errors, errors
    assert len(panel.marks) == 1 and panel.photos.count() == 1
    assert panel.view == 'TOP'
    with db.session() as session:
        service = InspectionService(session)
        snapshot = service.get(order_id)['inspection']
        mark = snapshot['marks'][0]
        assert (mark['view'], mark['body_element'], mark['normalized_x'], mark['normalized_y']) == ('TOP', 'ROOF', .44, .48)
        photo = snapshot['photos'][0]
        assert photo['damage_mark_id'] == mark['id']
        assert service.photo_path(order_id, photo['id']).read_bytes() == sample_photo.read_bytes()
        # Некорректная историческая запись: в печати должна оставаться явная оговорка.
        row = session.get(DamageMark, mark['id'])
        row.view, row.normalized_x, row.normalized_y = 'REAR', .5, .7
        session.commit()
        html, _ = inspection_print_parts(session, order_id)
        assert 'Крыша *' in html and 'ориентировочное положение' in html
    panel.refresh()
    assert panel.marks[0]['position_adjusted']

    def refine():
        active = qt_app.activeModalWidget()
        try:
            assert isinstance(active, DamageDialog)
            assert 'ориентировочное' in active.position_note.text()
            active.move_point(.43, .51)
            active.save()
        except Exception as exc:
            errors.append(exc)
            if active:
                active.reject()

    QTimer.singleShot(0, refine)
    panel.edit_mark()
    assert not errors, errors
    assert not panel.marks[0]['position_adjusted']
    assert panel.photos.count() == 1
    with db.session() as session:
        mark = session.get(DamageMark, mark['id'])
        assert (mark.view, mark.normalized_x, mark.normalized_y) == ('TOP', .43, .51)
    dialog.close()
