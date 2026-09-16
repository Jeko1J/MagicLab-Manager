import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QPushButton
from sqlalchemy import select

from app.models import User, UserRole, Order, OrderStatus
from app.services.access_service import AccessDenied
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.services.order_service import OrderService
from app.ui.main_window import MainWindow
from app.ui.dialogs.order_dialogs import OrderDialog, OrderDetailsDialog
from app.ui.dialogs.entity_dialogs import CustomerDialog, ServiceDialog, VehicleDialog
from app.ui.dialogs.user_dialogs import UserDialog, ResetPasswordDialog
from app.ui.dialogs.auth_dialogs import LoginDialog
from app.ui.pages.master_page import MasterOrderDialog
from app.ui.pages.users_page import UsersPage, AuditPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.statistics_page import StatisticsPage


@pytest.fixture
def staff(database):
    with database.session() as session:
        users = UserService(session)
        admin = users.create('admin', 'admin-password', 'Администратор', UserRole.ADMIN)
        master = users.create('master', 'master-password', 'Мастер', UserRole.MASTER)
        session.commit()
        owner = session.get(User, database.actor_id)
    return {UserRole.OWNER: owner, UserRole.ADMIN: admin, UserRole.MASTER: master}


@pytest.mark.parametrize('role,expected', [
    (UserRole.OWNER, ('Главная', 'Заказы', 'Расписание', 'Клиенты', 'Услуги', 'Статистика', 'Настройки', 'Пользователи', 'Журнал действий')),
    (UserRole.ADMIN, ('Заказы', 'Расписание', 'Клиенты', 'Услуги', 'Учётная запись')),
    (UserRole.MASTER, ('Мои заказы', 'Учётная запись')),
])
def test_navigation_and_hidden_actions(qt_app, database, staff, role, expected):
    database.sign_in(staff[role])
    window = MainWindow(database, staff[role].id)
    window.show()
    assert window.page_names == expected
    for index in range(len(window.pages)):
        window.navigate(index)
        qt_app.processEvents()
    if role != UserRole.OWNER:
        assert window.users is None and window.audit is None and window.statistics is None and window.dashboard is None
        visible = {button.text() for button in window.settings_page.findChildren(QPushButton) if not button.isHidden() and button.isVisibleTo(window.settings_page)}
        assert 'Создать резервную копию' not in visible and 'Восстановить из копии' not in visible
        assert 'Добавить учебные данные' not in visible and 'Экспортировать CSV' not in visible
    if role == UserRole.ADMIN:
        window.navigate(window.pages.index(window.services))
        texts = {button.text() for button in window.services.findChildren(QPushButton) if button.isVisible()}
        assert 'Добавить услугу' not in texts and 'Отключить услугу' not in texts
    if role == UserRole.MASTER:
        assert window.orders is None and window.customers is None and window.services is None
        with pytest.raises(AccessDenied):
            window.new_order()
    window.close()


@pytest.mark.parametrize('role', [UserRole.ADMIN, UserRole.MASTER])
def test_forbidden_dialogs_and_pages_reject_direct_open(qt_app, database, staff, role):
    database.sign_in(staff[role])
    for factory in (lambda: UserDialog(database), lambda: ResetPasswordDialog(database, staff[UserRole.OWNER].id),
                    lambda: ServiceDialog(database), lambda: UsersPage(database), lambda: AuditPage(database),
                    lambda: DashboardPage(database), lambda: StatisticsPage(database)):
        with pytest.raises(AccessDenied):
            factory()
    if role == UserRole.MASTER:
        for factory in (lambda: CustomerDialog(database), lambda: VehicleDialog(database, 1),
                        lambda: OrderDialog(database), lambda: OrderDetailsDialog(database, 1)):
            with pytest.raises(AccessDenied):
                factory()


def test_owner_creates_and_edits_user_through_dialog(qt_app, database):
    dialog = UserDialog(database)
    dialog.username.setText('new-master')
    dialog.full_name.setText('Новый мастер')
    dialog.password.setText('new-user-password')
    dialog.confirm.setText('new-user-password')
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    with database.session() as session:
        user_id = session.scalar(select(User.id).where(User.username == 'new-master'))
    edit = UserDialog(database, user_id)
    edit.username.setText('new-admin')
    edit.role.setCurrentIndex(edit.role.findData(UserRole.ADMIN))
    edit.save()
    with database.session() as session:
        assert session.get(User, user_id).role == UserRole.ADMIN
        assert session.get(User, user_id).username == 'new-admin'


def test_master_card_no_money_contacts_or_editing(qt_app, database, catalog, staff):
    from datetime import datetime
    from app.models import Customer, Vehicle
    with database.session() as session:
        order = OrderService(session).create_order(session.get(Customer, catalog['customer'].id), session.get(Vehicle, catalog['sedan'].id),
            datetime.now(), [catalog['wash'].id], assigned_master_id=staff[UserRole.MASTER].id)
        OrderService(session).change_status(order, OrderStatus.BOOKED)
        session.commit()
        order_id = order.id
    database.sign_in(staff[UserRole.MASTER])
    dialog = MasterOrderDialog(database, order_id)
    dialog.show()
    qt_app.processEvents()
    texts = '\n'.join(label.text() for label in dialog.findChildren(QLabel))
    assert '₽' not in texts and catalog['customer'].full_name not in texts and catalog['customer'].phone not in texts
    assert dialog.table.columnCount() == 2
    buttons = {button.text() for button in dialog.findChildren(QPushButton) if button.isVisible()}
    assert 'В работу' in buttons and 'Редактировать' not in buttons and 'Документы' not in buttons
    dialog.start.click()
    assert dialog.ready.isVisible() and not dialog.start.isVisible()
    dialog.ready.click()
    assert dialog.start.text() == 'Вернуть в работу'
    dialog.close()


def test_assignment_control_saves_master(qt_app, database, catalog, staff):
    dialog = OrderDialog(database)
    dialog.customer.setCurrentIndex(dialog.customer.findData(catalog['customer'].id))
    dialog.vehicle.setCurrentIndex(dialog.vehicle.findData(catalog['sedan'].id))
    dialog.services_table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    dialog.master.setCurrentIndex(dialog.master.findData(staff[UserRole.MASTER].id))
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    with database.session() as session:
        assert session.get(Order, dialog.result_id).assigned_master_id == staff[UserRole.MASTER].id


def test_switch_owner_to_master_rebuilds_ui(qt_app, database, staff, monkeypatch):
    window = MainWindow(database, database.actor_id)
    window.show()
    def login(dialog):
        dialog.username.setText('master')
        dialog.password.setText('master-password')
        dialog.attempt_login()
        return dialog.result()
    monkeypatch.setattr(LoginDialog, 'exec', login)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    window.logout()
    qt_app.processEvents()
    assert window.page_names == ('Мои заказы', 'Учётная запись')
    assert window.actor.id == staff[UserRole.MASTER].id
    assert window.users is None and window.orders is None
    with pytest.raises(AccessDenied):
        window.new_order()
    window.close()
