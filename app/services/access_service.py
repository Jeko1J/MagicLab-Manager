"""Проверка прав по текущей записи пользователя в БД."""
from dataclasses import dataclass

from sqlalchemy import select

from app.models import User, UserRole


class AccessDenied(ValueError):
    pass


@dataclass(frozen=True)
class Actor:
    id: int
    username: str
    full_name: str
    role: UserRole
    auth_version: int


OPERATIONAL = frozenset((UserRole.OWNER, UserRole.ADMIN))
ALL_ROLES = frozenset(UserRole)
PERMISSIONS = {
    'orders': OPERATIONAL, 'customers': OPERATIONAL, 'services_view': OPERATIONAL,
    'documents': OPERATIONAL, 'calendar_export': OPERATIONAL,
    'status': ALL_ROLES, 'account': ALL_ROLES,
    'inspection_view': ALL_ROLES, 'inspection_edit': OPERATIONAL, 'inspection_print': OPERATIONAL,
    'master_orders': frozenset((UserRole.MASTER,)),
    **{name: frozenset((UserRole.OWNER,)) for name in
       ('statistics', 'services_edit', 'users', 'audit', 'backup', 'restore', 'bulk_export', 'demo')},
}


def current_actor(session) -> Actor:
    if session is None:
        raise AccessDenied('Войдите в учётную запись')
    database = session.info.get('database')
    if database is None or database.auth_generation != session.info.get('auth_generation'):
        raise AccessDenied('Сеанс завершён. Войдите повторно')
    actor_id = session.info.get('actor_id')
    if actor_id is None:
        raise AccessDenied('Войдите в учётную запись')
    # ORM-кеш может хранить старую роль или признак блокировки.
    row = session.connection().execute(select(
        User.id, User.username, User.full_name, User.role, User.auth_version, User.is_active
    ).where(User.id == actor_id)).mappings().first()
    if not row or not row['is_active'] or row['auth_version'] != session.info.get('auth_version'):
        raise AccessDenied('Сеанс завершён. Войдите повторно')
    return Actor(row['id'], row['username'], row['full_name'], row['role'], row['auth_version'])


def require(session, permission: str) -> Actor:
    actor = current_actor(session)
    if actor.role not in PERMISSIONS.get(permission, ()):
        raise AccessDenied('Для вашей роли это действие недоступно')
    return actor


def can(actor: Actor, permission: str) -> bool:
    return actor.role in PERMISSIONS.get(permission, ())


def require_database(database, permission: str) -> Actor:
    with database.session() as session:
        return require(session, permission)
