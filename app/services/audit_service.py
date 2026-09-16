"""Журнал успешных изменений входит в ту же транзакцию, что и сами данные."""
from sqlalchemy import select

from app.models import AuditLog
from app.services.access_service import current_actor, require


def record(session, action: str, description: str = '', order_number: str = '', *, actor=None):
    actor = actor or current_actor(session)
    entry = AuditLog(user_id=actor.id, username=actor.username, full_name=actor.full_name,
                     action=action, description=description[:2000], order_number=order_number)
    session.add(entry)
    return entry


def record_event(database, action, description='', order_number=''):
    with database.session() as session:
        record(session, action, description, order_number)
        session.commit()


class AuditService:
    def __init__(self, session):
        self.session = session

    def search(self, text='', limit=500):
        require(self.session, 'audit')
        query = select(AuditLog)
        if text.strip():
            pattern = '%' + text.strip() + '%'
            query = query.where(AuditLog.order_number.ilike(pattern) | AuditLog.username.ilike(pattern)
                                | AuditLog.full_name.ilike(pattern) | AuditLog.action.ilike(pattern))
        return list(self.session.scalars(query.order_by(AuditLog.id.desc()).limit(max(1, min(limit, 5000)))))
