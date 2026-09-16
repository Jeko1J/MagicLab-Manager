from sqlalchemy import func, select

from app.models import User, UserRole, USER_ROLE_LABELS
from app.services.access_service import AccessDenied, require
from app.services.auth_service import hash_password
from app.services.audit_service import record


class UserService:
    def __init__(self, session):
        self.session = session

    def list_users(self):
        require(self.session, 'users')
        # Хеши паролей не выдаются экрану управления пользователями.
        return self.session.execute(select(User.id, User.username, User.full_name, User.role, User.is_active)
                                    .order_by(User.full_name, User.id)).all()

    def masters(self):
        require(self.session, 'orders')
        return self.session.execute(select(User.id, User.full_name).where(
            User.role == UserRole.MASTER, User.is_active.is_(True)).order_by(User.full_name)).all()

    def _validate(self, username, full_name, role, excluding=None):
        username, full_name = username.strip(), full_name.strip()
        if not username or len(username) > 80 or any(c.isspace() for c in username):
            raise ValueError('Имя пользователя: от 1 до 80 символов без пробелов')
        if not full_name or len(full_name) > 180:
            raise ValueError('Укажите имя сотрудника, не более 180 символов')
        try:
            role = UserRole(role)
        except (ValueError, TypeError):
            raise ValueError('Выберите роль сотрудника') from None
        duplicate = self.session.scalar(select(User.id).where(func.lower(User.username) == username.casefold(), User.id != excluding))
        if duplicate is not None:
            raise ValueError('Такое имя пользователя уже занято')
        return username, full_name, role

    def create(self, username, password, full_name, role):
        require(self.session, 'users')
        username, full_name, role = self._validate(username, full_name, role)
        user = User(username=username, full_name=full_name, role=role, password_hash=hash_password(password))
        self.session.add(user)
        self.session.flush()
        record(self.session, 'Создание пользователя', f'{username}; роль: {USER_ROLE_LABELS[role]}')
        return user

    def update(self, user_id, username, full_name, role, is_active):
        actor = require(self.session, 'users')
        user = self.session.get(User, user_id)
        if user is None:
            raise ValueError('Пользователь не найден')
        username, full_name, role = self._validate(username, full_name, role, user_id)
        if actor.id == user.id and (role != user.role or not is_active):
            raise ValueError('Нельзя заблокировать себя или изменить собственную роль')
        if user.role == UserRole.OWNER and user.is_active and (role != UserRole.OWNER or not is_active):
            other = self.session.scalar(select(User.id).where(User.role == UserRole.OWNER, User.is_active.is_(True), User.id != user.id).limit(1))
            if other is None:
                raise ValueError('Должен остаться хотя бы один активный руководитель')
        changes = []
        if user.username != username:
            changes.append(f'Логин: {user.username} → {username}')
        if user.full_name != full_name:
            changes.append('Изменено имя сотрудника')
        if user.role != role:
            changes.append(f'Роль: {USER_ROLE_LABELS[user.role]} → {USER_ROLE_LABELS[role]}')
        if user.is_active != bool(is_active):
            changes.append('Учётная запись разблокирована' if is_active else 'Учётная запись заблокирована')
        if user.role != role or user.is_active != bool(is_active):
            user.auth_version += 1
        user.username, user.full_name, user.role, user.is_active = username, full_name, role, bool(is_active)
        if changes:
            record(self.session, 'Изменение пользователя', f'{username}: ' + '; '.join(changes))
        self.session.flush()
        return user

    def reset_password(self, user_id, password):
        actor = require(self.session, 'users')
        user = self.session.get(User, user_id)
        if user is None:
            raise ValueError('Пользователь не найден')
        if user.id == actor.id:
            raise ValueError('Свой пароль измените в разделе «Учётная запись»')
        user.password_hash = hash_password(password)
        user.auth_version += 1
        record(self.session, 'Сброс пароля', f'Руководитель задал новый пароль сотруднику {user.username}')
        self.session.flush()
