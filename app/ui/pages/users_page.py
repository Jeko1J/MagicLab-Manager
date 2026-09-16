from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHeaderView, QMessageBox, QPushButton, QTableWidget, QLabel, QLineEdit

from app.models import USER_ROLE_LABELS
from app.services.access_service import require_database
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.ui.dialogs.user_dialogs import UserDialog, ResetPasswordDialog
from app.ui.pages.base import Page
from app.ui.widgets import configure_table, table_item, format_datetime, set_empty_text


class UsersPage(Page):
    def __init__(self, database, parent=None):
        require_database(database, 'users')
        super().__init__(database, 'Пользователи', parent)
        self.selection_buttons = []
        for text, slot in (('Новый сотрудник', self.add_user), ('Изменить', self.edit_user), ('Сбросить пароль', self.reset_password)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            self.header.addWidget(button)
            if text != 'Новый сотрудник':
                self.selection_buttons.append(button)
        self.toggle = QPushButton('Заблокировать')
        self.toggle.clicked.connect(self.toggle_user)
        self.header.addWidget(self.toggle)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(('Сотрудник', 'Имя пользователя', 'Роль', 'Доступ'))
        configure_table(self.table)
        for col in range(3):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 170)
        self.table.doubleClicked.connect(self.edit_user)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.root.addWidget(self.table, 1)
        note = QLabel('Сотрудники входят по очереди под личными учётными записями. Заблокированных пользователей и их действия не удаляют.')
        note.setWordWrap(True)
        self.root.addWidget(note)

    def selected_id(self):
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selection_changed(self):
        item = self.table.item(self.table.currentRow(), 3)
        for button in self.selection_buttons:
            button.setEnabled(item is not None)
        self.toggle.setEnabled(item is not None and self.selected_id() != self.database.actor_id)
        self.toggle.setText('Разблокировать' if item and not item.data(Qt.ItemDataRole.UserRole) else 'Заблокировать')
        self.selection_buttons[1].setEnabled(item is not None and self.selected_id() != self.database.actor_id)

    def refresh(self):
        with self.database.session() as session:
            users = UserService(session).list_users()
        self.table.setRowCount(len(users))
        for row, user in enumerate(users):
            for col, item in enumerate((table_item(user.full_name, user.id), table_item(user.username),
                    table_item(USER_ROLE_LABELS[user.role]), table_item('Разрешён' if user.is_active else 'Заблокирован', user.is_active))):
                self.table.setItem(row, col, item)
        self.selection_changed()

    def add_user(self):
        if UserDialog(self.database, parent=self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_user(self):
        user_id = self.selected_id()
        if user_id and UserDialog(self.database, user_id, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def reset_password(self):
        user_id = self.selected_id()
        if user_id and ResetPasswordDialog(self.database, user_id, self).exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, 'Пароль изменён', 'Новый пароль задан. Передайте его сотруднику лично.')

    def toggle_user(self):
        user_id = self.selected_id()
        if not user_id:
            return
        if QMessageBox.question(self, 'Доступ сотрудника', 'Изменить доступ выбранного сотрудника?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            with self.database.session() as session:
                service = UserService(session)
                user = next(row for row in service.list_users() if row.id == user_id)
                service.update(user.id, user.username, user.full_name, user.role, not user.is_active)
                session.commit()
        except ValueError as exc:
            QMessageBox.warning(self, 'Доступ сотрудника', str(exc))
        self.refresh()


class AuditPage(Page):
    def __init__(self, database, parent=None):
        require_database(database, 'audit')
        super().__init__(database, 'Журнал действий', parent)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Сотрудник, действие или номер заказа')
        self.search.setClearButtonEnabled(True)
        self.header.addWidget(self.search, 1)
        refresh = QPushButton('Обновить')
        refresh.clicked.connect(self.refresh)
        self.header.addWidget(refresh)
        self.root.addWidget(QLabel('Последние 500 подходящих записей. Пароли и их хеши в журнал не записываются.'))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(('Дата и время', 'Сотрудник', 'Действие', 'Заказ', 'Описание изменения'))
        configure_table(self.table)
        for col, width in ((0, 155), (1, 190), (2, 195), (3, 150)):
            self.table.setColumnWidth(col, width)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.root.addWidget(self.table, 1)
        set_empty_text(self.table, 'Записи не найдены. Измените поиск.')
        self.search.textChanged.connect(self.refresh)

    def refresh(self):
        with self.database.session() as session:
            entries = AuditService(session).search(self.search.text())
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            for col, value in enumerate((format_datetime(entry.occurred_at), f'{entry.full_name} ({entry.username})',
                                        entry.action, entry.order_number or '—', entry.description)):
                self.table.setItem(row, col, table_item(value))
