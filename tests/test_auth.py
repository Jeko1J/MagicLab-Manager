from app.models import User
from app.services.auth_service import AuthService, verify_password


def test_password_is_hashed_and_authentication_works(anonymous_session):
    session = anonymous_session
    user = AuthService(session).create_admin("admin", "strong-password", "Администратор")
    session.commit()
    assert user.password_hash != "strong-password"
    assert verify_password("strong-password", user.password_hash)
    assert AuthService(session).authenticate("admin", "strong-password").id == user.id
    assert AuthService(session).authenticate("admin", "wrong") is None
