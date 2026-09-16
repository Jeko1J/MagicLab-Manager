import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from decimal import Decimal
from PySide6.QtCore import QMarginsF, QSettings, Qt
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox
import pytest
from sqlalchemy import select

from app.main import create_application
from app.models import Order
from app.demo_data import seed_demo_business_data
from app.services.auth_service import AuthService
from app.ui.main_window import MainWindow
from app.ui.dialogs.order_dialogs import OrderDialog, OrderDetailsDialog, write_pdf
from app.ui.dialogs.entity_dialogs import CustomerDialog, ServiceDialog
from app.ui.dialogs.auth_dialogs import FirstRunDialog, LoginDialog, ChangePasswordDialog


def test_all_pages_populated(qt_app, database):
    database.seed_demo_services()
    assert seed_demo_business_data(database)
    window = MainWindow(database, database.actor_id)
    window.show()
    for index in range(len(window.pages)):
        window.navigate(index)
        qt_app.processEvents()
        assert window.stack.currentIndex() == index
    assert window.orders.table.rowCount() == 5
    assert window.customers.customers.rowCount() == 4
    window.close()


def test_brand_icon_is_inherited_by_main_window_and_dialogs(qt_app, database):
    from PySide6.QtCore import QSize
    from app.ui.application_icon import application_icon
    icon = application_icon()
    assert not icon.isNull()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        assert QSize(size, size) in icon.availableSizes()
        assert not icon.pixmap(size, size).isNull()
    window = MainWindow(database, database.actor_id)
    for widget in (FirstRunDialog(database), LoginDialog(database), CustomerDialog(database, parent=window), window):
        assert not widget.windowIcon().isNull()
        assert widget.windowIcon().cacheKey() == qt_app.windowIcon().cacheKey()
        widget.close()


@pytest.mark.skipif(os.name != 'nt', reason='Проверка API Windows')
def test_windows_has_separate_application_identity(qt_app):
    import ctypes
    from app.ui.application_icon import WINDOWS_APP_ID
    value = ctypes.c_void_p()
    getter = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID
    getter.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    getter.restype = ctypes.c_long
    assert getter(ctypes.byref(value)) == 0
    try:
        assert ctypes.wstring_at(value) == WINDOWS_APP_ID
    finally:
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(value)


def test_order_dialog_recalculates_and_saves(qt_app, database, catalog):
    dialog = OrderDialog(database)
    dialog.show()
    dialog.customer.setCurrentIndex(dialog.customer.findData(catalog['customer'].id))
    dialog.vehicle.setCurrentIndex(dialog.vehicle.findData(catalog['sedan'].id))
    dialog.services_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    dialog.services_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    qt_app.processEvents()
    assert dialog.total_price.text() == '6 000 ₽'
    dialog.prepayment.setValue(7000)
    dialog.save()
    assert 'превышать' in dialog.error_label.text()
    dialog.prepayment.setValue(500)
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.result_id


def test_customer_validation(qt_app, database):
    dialog = CustomerDialog(database)
    dialog.save()
    assert 'имя' in dialog._inline_error.text()
    dialog.name.setText('Тестовый клиент')
    dialog.phone.setText('123')
    dialog.save()
    assert 'телефона' in dialog._inline_error.text()
    dialog.accept()


def test_authentication_dialogs(qt_app, anonymous_database):
    database = anonymous_database
    first = FirstRunDialog(database)
    first.full_name.setText('Администратор')
    first.password.setText('local-test-password')
    first.confirm.setText('local-test-password')
    first.create_user()
    assert first.user_id
    login = LoginDialog(database)
    login.username.setText('admin')
    login.password.setText('wrong')
    login.attempt_login()
    assert login.user_id is None
    login.password.setText('local-test-password')
    login.attempt_login()
    assert login.user_id == first.user_id
    change = ChangePasswordDialog(database, first.user_id)
    change.old_password.setText('local-test-password')
    change.new_password.setText('new-local-password')
    change.confirm.setText('new-local-password')
    change.save()
    assert change.result() == QDialog.DialogCode.Accepted


def test_print_form_to_pdf(qt_app, database, tmp_path):
    database.seed_demo_services()
    seed_demo_business_data(database)
    with database.session() as session:
        order_id = session.scalar(select(Order.id))
    dialog = OrderDetailsDialog(database, order_id)
    path = tmp_path / 'order.pdf'
    write_pdf(dialog._document(), str(path))
    assert path.read_bytes().startswith(b'%PDF')
    assert path.stat().st_size > 1000
    dialog.close()


def test_unsaved_customer_confirmation(qt_app, database, monkeypatch):
    dialog = CustomerDialog(database)
    dialog.show()
    dialog.name.setText('Несохранённое имя')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.No)
    dialog.reject()
    assert dialog.isVisible()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    dialog.reject()
    assert not dialog.isVisible()


def test_logout_hides_protected_sections(qt_app, database, monkeypatch):
    window = MainWindow(database, database.actor_id)
    window.show()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(LoginDialog, 'exec', lambda self: QDialog.DialogCode.Rejected)
    window.logout()
    assert not window.isVisible()


def test_keyboard_service_selection(qt_app, database, catalog):
    dialog = OrderDialog(database)
    dialog.show()
    dialog.customer.setCurrentIndex(dialog.customer.findData(catalog['customer'].id))
    dialog.vehicle.setCurrentIndex(dialog.vehicle.findData(catalog['sedan'].id))
    dialog.services_table.setCurrentCell(0, 0)
    dialog.services_table.setFocus()
    QTest.keyClick(dialog.services_table, Qt.Key.Key_Space)
    assert len(dialog.selected_service_ids()) == 1
    dialog.accept()


@pytest.mark.parametrize('size', [(1366, 768), (1920, 1080)])
def test_compact_tables_fit_window(qt_app, database, size):
    database.seed_demo_services()
    seed_demo_business_data(database)
    window = MainWindow(database, database.actor_id)
    window.resize(*size)
    window.show()
    for index, table in ((1, window.orders.table), (2, window.schedule.table), (4, window.services.table)):
        window.navigate(index)
        for _ in range(3):
            qt_app.processEvents()
        assert window.size().width() == size[0]
        assert window.size().height() == size[1]
        assert table.horizontalScrollBar().maximum() == 0
        for row in range(table.rowCount()):
            assert table.rowHeight(row) >= 36
    window.close()


def test_long_customer_does_not_squeeze_services(qt_app, database, catalog):
    from app.models import Customer, Vehicle
    with database.session() as session:
        customer = session.get(Customer, catalog['customer'].id)
        customer.full_name = 'Александр Константинович Демонстрационный-Длиннофамильский'
        vehicle = session.get(Vehicle, catalog['sedan'].id)
        vehicle.brand = 'Mercedes-Benz'
        vehicle.model = 'V-Class Extra Long специальная комплектация'
        session.commit()
    dialog = OrderDialog(database)
    dialog.customer.setCurrentIndex(dialog.customer.findData(catalog['customer'].id))
    dialog.vehicle.setCurrentIndex(dialog.vehicle.findData(catalog['sedan'].id))
    dialog.show()
    for _ in range(3):
        qt_app.processEvents()
    assert dialog.customer.width() < 340
    assert dialog.customer.height() > 34
    assert dialog.services_table.columnWidth(1) > 300
    dialog.accept()


def test_validation_highlight_clears_on_recalculation(qt_app, database, catalog):
    dialog = OrderDialog(database)
    dialog.show()
    dialog.save()
    assert dialog.customer.property('invalid') is True
    assert not dialog.error_label.isHidden()
    dialog.customer.setCurrentIndex(dialog.customer.findData(catalog['customer'].id))
    assert dialog.customer.property('invalid') is False
    assert dialog.error_label.isHidden()
    dialog.accept()


def test_documents_menu_retains_existing_actions(qt_app, database):
    from PySide6.QtWidgets import QMenu
    database.seed_demo_services()
    seed_demo_business_data(database)
    with database.session() as session:
        order_id = session.scalar(select(Order.id))
    dialog = OrderDetailsDialog(database, order_id)
    assert [action.text() for action in dialog.findChild(QMenu).actions()] == [
        'Печать заказ-наряда', 'Сохранить PDF', 'Экспорт карточки в CSV']
    dialog.close()


def test_demo_history_is_chronological(database):
    from datetime import datetime
    from app.models import OrderStatus
    from app.repositories.orders import OrderRepository
    database.seed_demo_services()
    seed_demo_business_data(database)
    with database.session() as session:
        for order in OrderRepository(session).search():
            dates = [history.changed_at for history in order.status_history]
            assert dates == sorted(dates)
            assert 'Учебные данные' in order.comment
            if order.status in (OrderStatus.READY, OrderStatus.COMPLETED):
                assert order.scheduled_at < order.updated_at <= datetime.now()


def test_schedule_export_dialog_saves(qt_app, database, catalog, tmp_path, monkeypatch):
    from datetime import datetime
    from PySide6.QtCore import QDate
    from app.ui.dialogs.calendar_export_dialog import CalendarExportDialog
    from app.services.order_service import OrderService
    with database.session() as session:
        from app.models import Customer, Vehicle
        OrderService(session).create_order(session.get(Customer, catalog['customer'].id),
            session.get(Vehicle, catalog['sedan'].id), datetime(2026, 9, 4, 10), [catalog['wash'].id])
        session.commit()
    dialog = CalendarExportDialog(database, QDate(2026, 9, 4))
    assert dialog.date_from.date() == dialog.date_to.date() == QDate(2026, 9, 4)
    dialog.timezone.setCurrentIndex(dialog.timezone.findData('Asia/Vladivostok'))
    path = tmp_path / 'schedule.ics'
    monkeypatch.setattr(dialog, 'choose_export_path', lambda default: str(path))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: QMessageBox.StandardButton.Ok)
    dialog.export_calendar()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.exported_path == path
    assert b'DTSTART:20260904T000000Z' in path.read_bytes()


def test_schedule_export_empty_and_bad_period(qt_app, database, monkeypatch):
    from PySide6.QtCore import QDate
    from app.ui.dialogs.calendar_export_dialog import CalendarExportDialog
    dialog = CalendarExportDialog(database, QDate(2026, 9, 4))
    def unexpected_save(*args):
        pytest.fail('Must not ask for a path for invalid or empty export')
    monkeypatch.setattr(dialog, 'choose_export_path', unexpected_save)
    dialog.export_calendar()
    assert 'нет заказов' in dialog.error_label.text()
    dialog.date_from.setDate(QDate(2026, 9, 5))
    dialog.export_calendar()
    assert 'Начало периода' in dialog.error_label.text()
    dialog.reject()


def test_schedule_export_button_uses_selected_day(qt_app, database, monkeypatch):
    from PySide6.QtCore import QDate
    from app.ui.dialogs.calendar_export_dialog import CalendarExportDialog
    from app.ui.pages.schedule_page import SchedulePage
    selected = []
    monkeypatch.setattr(CalendarExportDialog, 'exec', lambda self: selected.append(self.date_from.date()))
    page = SchedulePage(database)
    page.calendar.setSelectedDate(QDate(2026, 10, 7))
    page.export_button.click()
    assert selected == [QDate(2026, 10, 7)]
