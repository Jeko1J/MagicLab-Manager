from pathlib import Path

from PySide6.QtCore import QDate, QSettings, QTimeZone
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from app.config import APP_NAME, EXPORT_DIR, ORGANIZATION_NAME
from app.services.calendar_export_service import CalendarExportService, save_calendar
from app.ui.widgets import ErrorLabel, fit_to_screen
from app.services.access_service import require_database
from app.services.audit_service import record_event


class CalendarExportDialog(QDialog):
    def __init__(self, database, selected_date: QDate, parent=None):
        require_database(database, 'calendar_export')
        super().__init__(parent)
        self.database = database
        self.settings = QSettings(ORGANIZATION_NAME, APP_NAME)
        self.exported_path: Path | None = None
        self.setWindowTitle('Экспорт расписания в календарь')
        self.setMinimumWidth(560)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        title = QLabel('Экспорт в календарь')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        note = QLabel('Файл .ics для календаря iPhone и других календарных приложений.')
        note.setObjectName('muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        form.setSpacing(10)
        self.date_from = QDateEdit(selected_date)
        self.date_to = QDateEdit(selected_date)
        for field in (self.date_from, self.date_to):
            field.setDisplayFormat('dd.MM.yyyy')
            field.setCalendarPopup(True)
        self.timezone = QComboBox()
        self._load_timezones()
        form.addRow('С даты', self.date_from)
        form.addRow('По дату включительно', self.date_to)
        form.addRow('Часовой пояс студии', self.timezone)
        layout.addLayout(form)
        for text in (
            'Время записи считается временем выбранного пояса. Окончание — по суммарной длительности услуг, без перерывов.',
            'В файл попадут номера заказов, автомобили, гос. номера, услуги и статусы. ФИО, телефоны, суммы и внутренние комментарии не включаются. Отменённые заказы пропускаются.',
            'Это разовая копия, не синхронизация. Повторный импорт может создать дубликаты. Файл не зашифрован — передавайте его только сотрудникам.',
        ):
            label = QLabel(text)
            label.setObjectName('muted')
            label.setWordWrap(True)
            layout.addWidget(label)
        self.error_label = ErrorLabel()
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = QPushButton('Сохранить .ics')
        self.save_button.setObjectName('primary')
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.clicked.connect(self.export_calendar)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for signal in (self.date_from.dateChanged, self.date_to.dateChanged, self.timezone.currentIndexChanged):
            signal.connect(lambda *_: self.error_label.clear())
        fit_to_screen(self)

    def _load_timezones(self):
        zones = (
            ('Калининград', 'Europe/Kaliningrad'), ('Москва', 'Europe/Moscow'),
            ('Самара', 'Europe/Samara'), ('Екатеринбург', 'Asia/Yekaterinburg'),
            ('Омск', 'Asia/Omsk'), ('Красноярск', 'Asia/Krasnoyarsk'),
            ('Иркутск', 'Asia/Irkutsk'), ('Якутск', 'Asia/Yakutsk'),
            ('Владивосток', 'Asia/Vladivostok'), ('Магадан', 'Asia/Magadan'),
            ('Камчатка', 'Asia/Kamchatka'), ('Всемирное время (UTC)', 'UTC'),
        )
        system_id = bytes(QTimeZone.systemTimeZoneId()).decode('ascii', errors='replace')
        saved_id = str(self.settings.value('calendar_export/timezone', system_id))
        for label, identifier in zones:
            if QTimeZone(identifier.encode('ascii')).isValid():
                self.timezone.addItem(label, identifier)
        for identifier, label in ((system_id, 'Часовой пояс Windows'), (saved_id, 'Ранее выбранный пояс')):
            if self.timezone.findData(identifier) < 0 and identifier.isascii() and QTimeZone(identifier.encode('ascii')).isValid():
                self.timezone.addItem(f'{label} ({identifier})', identifier)
        index = self.timezone.findData(saved_id)
        if index < 0:
            self.timezone.insertItem(0, 'Выберите часовой пояс', None)
            index = 0
        self.timezone.setCurrentIndex(index)

    def choose_export_path(self, default: Path) -> str:
        dialog = QFileDialog(self, 'Сохранить расписание', str(default.parent))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter('Календарь iCalendar (*.ics)')
        dialog.setDefaultSuffix('ics')
        dialog.selectFile(default.name)
        return dialog.selectedFiles()[0] if dialog.exec() == QDialog.DialogCode.Accepted else ''

    def export_calendar(self):
        self.error_label.clear()
        start, end = self.date_from.date().toPython(), self.date_to.date().toPython()
        try:
            with self.database.session() as session:
                result = CalendarExportService(session).prepare(start, end, self.timezone.currentData())
            if not result.event_count:
                self.error_label.setText('В выбранном периоде нет заказов для экспорта. Отменённые заказы не включаются.')
                return
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            chosen = self.choose_export_path(EXPORT_DIR / f'magiclab_schedule_{start:%Y%m%d}_{end:%Y%m%d}.ics')
            if not chosen:
                return
            save_calendar(Path(chosen), result)
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        except OSError:
            self.error_label.setText('Не удалось сохранить файл. Проверьте путь, права доступа и свободное место.')
            return
        self.exported_path = Path(chosen)
        record_event(self.database, 'Экспорт расписания', f'Период {start:%d.%m.%Y} — {end:%d.%m.%Y}; событий: {result.event_count}')
        self.settings.setValue('calendar_export/timezone', self.timezone.currentData())
        QMessageBox.information(self, 'Расписание сохранено',
            f'Событий: {result.event_count}. Пропущено отменённых: {result.skipped_cancelled}.\n'
            f'Файл: {chosen}\n\nПередайте файл на iPhone и импортируйте, например, из вложения в приложении «Почта». '
            'Изменения расписания автоматически не передаются.')
        self.accept()
