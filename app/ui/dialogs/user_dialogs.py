from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from app.models import USER_ROLE_LABELS, UserRole
from app.services.access_service import require_database
from app.services.user_service import UserService
from app.ui.dialogs.entity_dialogs import FormDialog


class UserDialog(FormDialog):
    def __init__(self, database, user_id=None, parent=None):
        require_database(database, 'users')
        super().__init__('Новый сотрудник' if user_id is None else 'Учётная запись сотрудника', parent)
        self.database, self.user_id = database, user_id
        self.username, self.full_name = QLineEdit(), QLineEdit()
        self.role = QComboBox()
        for role, label in USER_ROLE_LABELS.items():
            self.role.addItem(label, role)
        self.role.setCurrentIndex(self.role.findData(UserRole.MASTER))
        self.active = QCheckBox('Доступ к программе разрешён')
        self.active.setChecked(True)
        self.password, self.confirm = QLineEdit(), QLineEdit()
        for field in (self.password, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        self.form.addRow('Имя сотрудника', self.full_name)
        self.form.addRow('Имя пользователя', self.username)
        self.form.addRow('Роль', self.role)
        self.form.addRow('', self.active)
        if user_id is None:
            self.form.addRow('Пароль', self.password)
            self.form.addRow('Повторите пароль', self.confirm)
            self.active.hide()
        else:
            with database.session() as session:
                row = next((user for user in UserService(session).list_users() if user.id == user_id), None)
            if row is None:
                raise ValueError('Пользователь не найден')
            self.username.setText(row.username)
            self.full_name.setText(row.full_name)
            self.role.setCurrentIndex(self.role.findData(row.role))
            self.active.setChecked(row.is_active)
        self.add_footer()

    def save(self):
        try:
            with self.database.session() as session:
                service = UserService(session)
                if self.user_id is None:
                    if self.password.text() != self.confirm.text():
                        raise ValueError('Пароли не совпадают')
                    service.create(self.username.text(), self.password.text(), self.full_name.text(), self.role.currentData())
                else:
                    service.update(self.user_id, self.username.text(), self.full_name.text(), self.role.currentData(), self.active.isChecked())
                session.commit()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()


class ResetPasswordDialog(FormDialog):
    def __init__(self, database, user_id, parent=None):
        require_database(database, 'users')
        super().__init__('Сброс пароля сотрудника', parent)
        self.database, self.user_id = database, user_id
        self.password, self.confirm = QLineEdit(), QLineEdit()
        for field in (self.password, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        self.form.addRow('Новый пароль', self.password)
        self.form.addRow('Повторите пароль', self.confirm)
        self.add_footer('Задать пароль')

    def save(self):
        try:
            if self.password.text() != self.confirm.text():
                raise ValueError('Пароли не совпадают')
            with self.database.session() as session:
                UserService(session).reset_password(self.user_id, self.password.text())
                session.commit()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()
