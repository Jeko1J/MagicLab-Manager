import pytest
from PySide6.QtWidgets import QDialog
from sqlalchemy import func, select

from app.models import Customer
from app.repositories.customers import CustomerRepository
from app.ui.dialogs.entity_dialogs import CustomerDialog


@pytest.mark.parametrize('editing', [False, True])
def test_duplicate_phone_stays_in_form(qt_app, database, editing):
    with database.session() as session:
        repo = CustomerRepository(session)
        first = repo.create('Первый клиент', '89991234567')
        second = repo.create('Второй клиент', '89997654321') if editing else None
        session.commit()
        edit_id = second.id if second else None
        first_id = first.id

    dialog = CustomerDialog(database, edit_id)
    dialog.name.setText('Новое имя')
    dialog.phone.setText('+7 (999) 123-45-67')
    dialog.save()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert 'телефоном уже существует' in dialog._inline_error.text()
    with database.session() as session:
        assert session.scalar(select(func.count(Customer.id))) == (2 if editing else 1)
        assert session.get(Customer, first_id).full_name == 'Первый клиент'
        if editing:
            assert session.get(Customer, edit_id).phone == '+7 (999) 765-43-21'
    QDialog.reject(dialog)


def test_edit_customer_keeps_own_phone(qt_app, database):
    with database.session() as session:
        customer = CustomerRepository(session).create('Клиент', '89991234567')
        session.commit()
        customer_id = customer.id
    dialog = CustomerDialog(database, customer_id)
    dialog.name.setText('Изменённое имя')
    dialog.save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    with database.session() as session:
        assert session.get(Customer, customer_id).full_name == 'Изменённое имя'
