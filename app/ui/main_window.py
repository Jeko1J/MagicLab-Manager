from __future__ import annotations

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from app.config import APP_NAME, ORGANIZATION_NAME
from app.models import USER_ROLE_LABELS, UserRole
from app.services.access_service import AccessDenied, can, require_database
from app.services.auth_service import AuthService
from app.services.audit_service import record_event
from app.ui.icons import navigation_icon
from app.ui.widgets import BrandMark, fit_to_screen
from app.ui.dialogs.auth_dialogs import FirstRunDialog, LoginDialog
from app.ui.dialogs.order_dialogs import OrderDetailsDialog, OrderDialog
from app.ui.pages import CustomersPage, DashboardPage, OrdersPage, SchedulePage, ServicesPage, SettingsPage, StatisticsPage
from app.ui.pages.master_page import MasterPage, MasterOrderDialog
from app.ui.pages.users_page import UsersPage, AuditPage


class MainWindow(QMainWindow):
    def __init__(self, database, user_id: int, parent=None):
        super().__init__(parent)
        self.database, self.user_id = database, user_id
        self.actor = require_database(database, 'account')
        if self.actor.id != user_id:
            raise AccessDenied('Окно должно принадлежать текущей учётной записи')
        self.settings = QSettings(ORGANIZATION_NAME, APP_NAME)
        self._switching = False
        self._force_close = False
        self.shortcuts = []
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 700)
        self.resize(1366, 768)
        self.build_ui()
        geometry = self.settings.value('main/geometry')
        if geometry:
            self.restoreGeometry(geometry)
        fit_to_screen(self)
        self.navigate(0)
        self.session_timer = QTimer(self)
        self.session_timer.setInterval(2000)
        self.session_timer.timeout.connect(self.check_session)
        self.session_timer.start()

    def build_ui(self):
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 12, 0, 12)
        side.setSpacing(3)
        brand = QVBoxLayout()
        brand.setContentsMargins(20, 0, 20, 14)
        brand.addWidget(BrandMark())
        brand_name = QLabel('MagicLab Manager')
        brand_name.setObjectName('muted')
        brand.addWidget(brand_name)
        side.addLayout(brand)
        self.stack = QStackedWidget()
        self.dashboard = self.orders = self.schedule = self.customers = self.services = self.statistics = None
        self.master_page = self.users = self.audit = None
        specs = []
        if self.actor.role == UserRole.OWNER:
            self.dashboard = DashboardPage(self.database)
            specs.append(('Главная', self.dashboard, 'statistics', 0))
        if can(self.actor, 'orders'):
            self.orders, self.schedule = OrdersPage(self.database), SchedulePage(self.database)
            self.customers, self.services = CustomersPage(self.database), ServicesPage(self.database)
            specs.extend((('Заказы', self.orders, 'orders', 1), ('Расписание', self.schedule, 'orders', 2),
                          ('Клиенты', self.customers, 'customers', 3), ('Услуги', self.services, 'services_view', 4)))
        if self.actor.role == UserRole.MASTER:
            self.master_page = MasterPage(self.database)
            specs.append(('Мои заказы', self.master_page, 'master_orders', 1))
        if can(self.actor, 'statistics'):
            self.statistics = StatisticsPage(self.database)
            specs.append(('Статистика', self.statistics, 'statistics', 5))
        self.settings_page = SettingsPage(self.database, self.user_id)
        specs.append(('Настройки' if self.actor.role == UserRole.OWNER else 'Учётная запись', self.settings_page, 'account', 6))
        if can(self.actor, 'users'):
            self.users, self.audit = UsersPage(self.database), AuditPage(self.database)
            specs.extend((('Пользователи', self.users, 'users', 3), ('Журнал действий', self.audit, 'audit', 4)))
        self.pages = tuple(page for _, page, _, _ in specs)
        self.page_permissions = tuple(permission for _, _, permission, _ in specs)
        self.page_names = tuple(title for title, _, _, _ in specs)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for index, (title, page, permission, icon) in enumerate(specs):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
            button = QPushButton(title)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.setIcon(navigation_icon(icon))
            button.clicked.connect(lambda _checked=False, value=index: self.navigate(value))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            side.addWidget(button)
        side.addStretch()
        self.account_hint = QLabel(f'{self.actor.full_name}\n{USER_ROLE_LABELS[self.actor.role]}')
        self.account_hint.setTextFormat(Qt.TextFormat.PlainText)
        self.account_hint.setWordWrap(True)
        self.account_hint.setObjectName('muted')
        self.account_hint.setContentsMargins(12, 0, 12, 8)
        side.addWidget(self.account_hint)
        logout = QPushButton('Сменить сотрудника')
        logout.setObjectName('nav')
        logout.setIcon(navigation_icon(7))
        logout.clicked.connect(self.logout)
        side.addWidget(logout)
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f'{USER_ROLE_LABELS[self.actor.role]} · Локальная база данных подключена')
        for page in (self.dashboard, self.orders, self.schedule, self.customers, self.master_page):
            if page is not None:
                page.open_order.connect(self.open_order)
        if self.orders is not None:
            self.orders.new_order.connect(self.new_order)
            self.shortcuts = [QShortcut(QKeySequence.StandardKey.New, self, activated=self.new_order),
                              QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_search)]
        elif self.master_page is not None:
            self.shortcuts = [QShortcut(QKeySequence.StandardKey.Find, self, activated=self.focus_search)]
        self.settings_page.database_restored.connect(lambda: QTimer.singleShot(0, self.reauthenticate))
        self.settings_page.data_changed.connect(self.refresh_all)

    def check_session(self):
        if self._switching:
            return
        try:
            require_database(self.database, 'account')
        except AccessDenied:
            self.reauthenticate()

    def reauthenticate(self):
        if self._switching:
            return
        self._switching = True
        self.session_timer.stop()
        self.hide()
        for dialog in self.findChildren(QDialog):
            dialog.done(QDialog.DialogCode.Rejected)
        for shortcut in self.shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts = []
        self.database.sign_out()
        old = self.takeCentralWidget()
        if old:
            old.hide()
            old.deleteLater()
        self.nav_group.deleteLater()
        with self.database.session() as session:
            has_users = AuthService(session).has_users()
        dialog = LoginDialog(self.database) if has_users else FirstRunDialog(self.database)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.user_id = dialog.user_id
            self.actor = require_database(self.database, 'account')
            self.build_ui()
            self.navigate(0)
            self.show()
            self.session_timer.start()
        else:
            self._force_close = True
            self.close()
        self._switching = False

    def navigate(self, index):
        if not 0 <= index < len(self.pages):
            raise AccessDenied('Раздел недоступен')
        require_database(self.database, self.page_permissions[index])
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.pages[index].refresh()
        if self.page_permissions[index] == 'statistics':
            record_event(self.database, 'Просмотр статистики', self.page_names[index])

    def refresh_all(self):
        for page, permission in zip(self.pages, self.page_permissions):
            require_database(self.database, permission)
            page.refresh()

    def new_order(self):
        require_database(self.database, 'orders')
        dialog = OrderDialog(self.database, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_all()
            self.statusBar().showMessage('Заказ сохранён', 4000)
            self.open_order(dialog.result_id)

    def open_order(self, order_id):
        actor = require_database(self.database, 'account')
        dialog_type = MasterOrderDialog if actor.role == UserRole.MASTER else OrderDetailsDialog
        dialog = dialog_type(self.database, order_id, self)
        dialog.exec()
        if dialog.changed:
            self.refresh_all()

    def focus_search(self):
        page = self.master_page or self.orders
        if page is not None:
            self.navigate(self.pages.index(page))
            page.search.setFocus()
            page.search.selectAll()

    def logout(self):
        answer = QMessageBox.question(self, 'Смена сотрудника', 'Выйти из учётной записи?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            record_event(self.database, 'Выход', 'Смена сотрудника')
            self.reauthenticate()

    def closeEvent(self, event):
        self.settings.setValue('main/geometry', self.saveGeometry())
        self.session_timer.stop()
        if not self._force_close and not self._switching:
            if self.orders is not None:
                self.orders.save_column_widths()
            try:
                record_event(self.database, 'Выход', 'Приложение закрыто')
            except AccessDenied:
                pass
            self.database.sign_out()
        event.accept()
