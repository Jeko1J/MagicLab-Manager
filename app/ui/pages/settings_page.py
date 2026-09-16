from __future__ import annotations

import csv
from datetime import datetime, time
from pathlib import Path

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.config import BACKUP_DIR, DB_PATH, EXPORT_DIR
from app.models import ORDER_STATUS_LABELS, User
from app.repositories.orders import OrderRepository
from app.services.backup_service import BackupError, create_backup, restore_backup
from app.demo_data import seed_demo_business_data
from app.ui.dialogs.auth_dialogs import ChangePasswordDialog
from app.ui.pages.base import Page
from app.ui.widgets import format_datetime
from app.services.access_service import require_database, can
from app.services.audit_service import record_event


class SettingsPage(Page):
    database_restored = Signal()
    data_changed = Signal()

    def __init__(self, database, user_id: int, parent=None) -> None:
        actor = require_database(database, 'account')
        if actor.id != user_id:
            from app.services.access_service import AccessDenied
            raise AccessDenied('Открыта чужая учётная запись')
        super().__init__(database, "Настройки" if can(actor, 'backup') else "Учётная запись", parent)
        self.user_id = user_id
        self.account_label = QLabel()
        self.root.addWidget(self.account_label)
        backup_group = QGroupBox("Резервные копии")
        backup_layout = QVBoxLayout(backup_group)
        backup_note = QLabel(f"Рабочая база: {DB_PATH}\nПолная ZIP-копия включает базу, фотографии осмотров и сведения о версии.")
        backup_note.setObjectName("muted")
        backup_note.setWordWrap(True)
        backup_actions = QHBoxLayout()
        create_button = QPushButton("Создать резервную копию")
        create_button.setObjectName("primary")
        restore_button = QPushButton("Восстановить из копии")
        create_button.clicked.connect(self.create_backup)
        restore_button.clicked.connect(self.restore_backup)
        backup_actions.addWidget(create_button)
        backup_actions.addWidget(restore_button)
        backup_actions.addStretch()
        backup_layout.addWidget(backup_note)
        backup_layout.addLayout(backup_actions)

        export_group = QGroupBox("Экспорт списка заказов")
        export_layout = QHBoxLayout(export_group)
        self.export_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.export_to = QDateEdit(QDate.currentDate())
        for field in (self.export_from, self.export_to):
            field.setCalendarPopup(True)
            field.setDisplayFormat("dd.MM.yyyy")
        export_button = QPushButton("Экспортировать CSV")
        export_button.clicked.connect(self.export_orders)
        export_layout.addWidget(QLabel("С"))
        export_layout.addWidget(self.export_from)
        export_layout.addWidget(QLabel("по"))
        export_layout.addWidget(self.export_to)
        export_layout.addWidget(export_button)
        export_layout.addStretch()

        account_group = QGroupBox("Учётная запись")
        account_layout = QHBoxLayout(account_group)
        account_layout.addWidget(QLabel("Пароль для входа в программу на этом компьютере."))
        password_button = QPushButton("Изменить пароль")
        password_button.clicked.connect(self.change_password)
        account_layout.addWidget(password_button)
        account_layout.addStretch()
        demo_group = QGroupBox("Демонстрация")
        demo_layout = QHBoxLayout(demo_group)
        demo_note = QLabel("Добавляет только в пустую клиентскую базу явно отмеченные учебные записи.")
        demo_note.setObjectName("muted")
        demo_note.setWordWrap(True)
        demo_button = QPushButton("Добавить учебные данные")
        demo_button.clicked.connect(self.add_demo_data)
        demo_layout.addWidget(demo_note)
        demo_layout.addWidget(demo_button)
        demo_layout.addStretch()
        for group in (backup_group, export_group, account_group, demo_group):
            group.setMaximumWidth(1040)
        self.root.addWidget(backup_group)
        self.root.addWidget(export_group)
        self.root.addWidget(account_group)
        self.root.addWidget(demo_group)
        backup_group.setVisible(can(actor, 'backup'))
        export_group.setVisible(can(actor, 'bulk_export'))
        demo_group.setVisible(can(actor, 'demo'))
        self.root.addStretch()

    def refresh(self) -> None:
        with self.database.session() as session:
            user = session.get(User, self.user_id)
            self.account_label.setText(f"Сотрудник: {user.full_name}" if user else "Проверка приложения")

    def create_backup(self) -> None:
        require_database(self.database, 'backup')
        try:
            with self.database.session() as session:
                path = create_backup(DB_PATH, BACKUP_DIR, session=session)
                session.commit()
        except (BackupError, OSError) as exc:
            QMessageBox.warning(self, "Резервная копия", str(exc))
            return
        QMessageBox.information(self, "Резервная копия создана", f"Копия сохранена:\n{path}")

    def restore_backup(self) -> None:
        require_database(self.database, 'restore')
        path, _ = QFileDialog.getOpenFileName(self, "Выберите резервную копию", str(BACKUP_DIR), "Копия MagicLab (*.zip *.db);;ZIP с фотографиями (*.zip);;Старая база без фото (*.db)")
        if not path:
            return
        answer = QMessageBox.warning(
            self, "Восстановление базы",
            "Текущая база и фотографии будут заменены. Перед заменой будет создана полная страховочная ZIP-копия. Потребуется повторный вход. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with self.database.session() as session:
                _restored, safety = restore_backup(DB_PATH, Path(path), BACKUP_DIR, session=session)
        except (BackupError, OSError) as exc:
            QMessageBox.warning(self, "Восстановление базы", str(exc))
            return
        QMessageBox.information(self, "База восстановлена", f"База и фотографии восстановлены. Наличие и читаемость фотографий проверены.\nСтраховочная копия: {safety}")
        self.database_restored.emit()

    def export_orders(self) -> None:
        require_database(self.database, 'bulk_export')
        date_from = self.export_from.date().toPython()
        date_to = self.export_to.date().toPython()
        if date_from > date_to:
            QMessageBox.warning(self, "Экспорт", "Начало периода не может быть позже окончания")
            return
        default = EXPORT_DIR / f"orders_{date_from:%Y%m%d}_{date_to:%Y%m%d}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт списка заказов", str(default), "CSV (*.csv)")
        if not path:
            return
        with self.database.session() as session:
            orders = OrderRepository(session).search(date_from=date_from, date_to=date_to)
            rows = [
                (
                    order.public_number, format_datetime(order.scheduled_at), order.customer.full_name,
                    order.customer.phone, f"{order.vehicle.brand} {order.vehicle.model}",
                    order.vehicle.license_plate, str(order.total_price), str(order.prepayment),
                    ORDER_STATUS_LABELS[order.status], ", ".join(item.service_name_snapshot for item in order.items),
                )
                for order in orders
            ]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(("Номер", "Дата и время", "Клиент", "Телефон", "Автомобиль", "Гос. номер", "Стоимость", "Предоплата", "Статус", "Услуги"))
                writer.writerows(rows)
        except OSError:
            QMessageBox.warning(self, "Экспорт", "Не удалось записать выбранный файл")
            return
        record_event(self.database, 'Экспорт заказов', f'CSV; период {date_from:%d.%m.%Y} — {date_to:%d.%m.%Y}; заказов: {len(rows)}')
        QMessageBox.information(self, "Экспорт завершён", f"Экспортировано заказов: {len(rows)}\n{path}")

    def change_password(self) -> None:
        require_database(self.database, 'account')
        if ChangePasswordDialog(self.database, self.user_id, self).exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Пароль изменён", "Новый пароль сохранён")

    def add_demo_data(self) -> None:
        require_database(self.database, 'demo')
        answer = QMessageBox.question(
            self, "Учебные данные",
            "Добавить учебных клиентов, автомобили и заказы? Действие доступно только при пустой клиентской базе.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not seed_demo_business_data(self.database):
            QMessageBox.information(self, "Учебные данные", "Клиентская база уже содержит записи или прайс-лист неполон.")
            return
        self.data_changed.emit()
        QMessageBox.information(self, "Учебные данные", "Учебные клиенты, автомобили и заказы добавлены.")
