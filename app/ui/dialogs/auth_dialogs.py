from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.services.auth_service import AuthService
from app.ui.widgets import ErrorLabel


class BaseAuthDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setMinimumWidth(460)
        self.error_label = ErrorLabel()

    def show_error(self, text: str) -> None:
        self.error_label.setText(text)


class LoginDialog(BaseAuthDialog):
    def __init__(self, database, parent=None) -> None:
        super().__init__(parent)
        self.database = database
        self.user_id: int | None = None
        self.setWindowTitle("Вход — MagicLab Manager")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("Magic Lab Manager")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Вход для сотрудников студии")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        form = QFormLayout()
        form.setSpacing(10)
        self.username = QLineEdit()
        self.username.setPlaceholderText("Имя пользователя")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Пароль")
        form.addRow("Пользователь", self.username)
        form.addRow("Пароль", self.password)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        login = QPushButton("Войти")
        login.setObjectName("primary")
        login.clicked.connect(self.attempt_login)
        buttons.addButton(login, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.password.returnPressed.connect(self.attempt_login)
        self.username.setFocus()

    def attempt_login(self) -> None:
        with self.database.session() as session:
            user = AuthService(session).authenticate(self.username.text(), self.password.text())
            if user is None:
                session.commit()
                self.show_error("Неверное имя пользователя или пароль")
                self.password.selectAll()
                self.password.setFocus()
                return
            self.user_id = user.id
            session.commit()
            self.database.sign_in(user)
        self.accept()


class FirstRunDialog(BaseAuthDialog):
    def __init__(self, database, parent=None) -> None:
        super().__init__(parent)
        self.database = database
        self.user_id: int | None = None
        self.setWindowTitle("Первый запуск — MagicLab Manager")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)
        title = QLabel("Создание руководителя")
        title.setObjectName("pageTitle")
        note = QLabel("Первая учётная запись получает полный доступ. Затем руководитель сможет добавить остальных сотрудников.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(note)
        form = QFormLayout()
        form.setSpacing(10)
        self.full_name = QLineEdit()
        self.username = QLineEdit("admin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Имя руководителя", self.full_name)
        form.addRow("Имя пользователя", self.username)
        form.addRow("Пароль", self.password)
        form.addRow("Повторите пароль", self.confirm)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        create = QPushButton("Создать и войти")
        create.setObjectName("primary")
        create.clicked.connect(self.create_user)
        buttons.addButton(create, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.full_name.setFocus()

    def create_user(self) -> None:
        if self.password.text() != self.confirm.text():
            self.show_error("Пароли не совпадают")
            return
        try:
            with self.database.session() as session:
                user = AuthService(session).create_admin(
                    self.username.text(), self.password.text(), self.full_name.text()
                )
                session.commit()
                self.user_id = user.id
                self.database.sign_in(user)
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.accept()


class ChangePasswordDialog(BaseAuthDialog):
    def __init__(self, database, user_id: int, parent=None) -> None:
        super().__init__(parent)
        self.database = database
        self.user_id = user_id
        self.setWindowTitle("Изменение пароля")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel('Изменение пароля')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        form = QFormLayout()
        self.old_password = QLineEdit()
        self.new_password = QLineEdit()
        self.confirm = QLineEdit()
        for field in (self.old_password, self.new_password, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Текущий пароль", self.old_password)
        form.addRow("Новый пароль", self.new_password)
        form.addRow("Повторите пароль", self.confirm)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        save = QPushButton("Изменить пароль")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self) -> None:
        if self.new_password.text() != self.confirm.text():
            self.show_error("Новые пароли не совпадают")
            return
        try:
            with self.database.session() as session:
                from app.models import User
                user = session.get(User, self.user_id)
                if user is None:
                    raise ValueError("Пользователь не найден")
                AuthService(session).change_password(user, self.old_password.text(), self.new_password.text())
                session.commit()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.accept()
