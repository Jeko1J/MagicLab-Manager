from __future__ import annotations

import hashlib
import hmac
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User, UserRole, AuditLog
from app.services.access_service import Actor, AccessDenied, current_actor
from app.services.audit_service import record

ITERATIONS = 310_000


def hash_password(password: str) -> str:
    if not password or not password.strip():
        raise ValueError("Пароль не может быть пустым")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def has_users(self) -> bool:
        return bool(self.session.scalar(select(func.count(User.id))))

    def create_admin(self, username: str, password: str, full_name: str) -> User:
        if self.has_users():
            raise AccessDenied('Первичная учётная запись уже создана. Новых сотрудников добавляет руководитель')
        username = username.strip()
        full_name = full_name.strip()
        if not username:
            raise ValueError("Введите имя пользователя")
        if not full_name:
            raise ValueError("Введите имя администратора")
        if not password or not password.strip():
            raise ValueError("Введите пароль")
        if self.session.scalar(select(User).where(User.username == username)):
            raise ValueError("Пользователь с таким именем уже существует")
        user = User(username=username, full_name=full_name, password_hash=hash_password(password), role=UserRole.OWNER)
        self.session.add(user)
        self.session.flush()
        record(self.session, 'Первый руководитель', 'Создана локальная учётная запись руководителя', actor=user)
        return user

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.session.scalar(select(User).where(func.lower(User.username) == username.strip().casefold()))
        if user and user.is_active and verify_password(password, user.password_hash):
            record(self.session, 'Вход', 'Успешный вход в приложение', actor=user)
            return user
        self.session.add(AuditLog(user_id=None, username='—', full_name='Неустановленный пользователь',
            action='Отказ во входе', description='Неверные учётные данные или учётная запись заблокирована'))
        return None

    def change_password(self, user: User, old_password: str, new_password: str) -> None:
        actor = current_actor(self.session)
        if actor.id != user.id:
            raise AccessDenied('Можно изменить только собственный пароль')
        if not verify_password(old_password, user.password_hash):
            raise ValueError("Текущий пароль указан неверно")
        if not new_password or not new_password.strip():
            raise ValueError("Новый пароль не может быть пустым")
        user.password_hash = hash_password(new_password)
        record(self.session, 'Смена пароля', 'Пользователь изменил собственный пароль')
        self.session.flush()
