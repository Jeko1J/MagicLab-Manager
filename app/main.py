from __future__ import annotations

import argparse
import logging
import sys
import os
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QLockFile, QTimer, QTranslator, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtGui import QFont, QFontDatabase, QPalette, QColor

from app.config import APP_NAME, DATA_DIR, ORGANIZATION_NAME, RESOURCE_DIR, ensure_directories
from app.database import Database
from app.services.auth_service import AuthService
from app.ui.dialogs.auth_dialogs import FirstRunDialog, LoginDialog
from app.ui.main_window import MainWindow
from app.ui.styles import APP_STYLESHEET
from app.ui.styles import COLORS
from app.ui.application_icon import application_icon, configure_windows_identity


def configure_logging() -> None:
    ensure_directories()
    logging.basicConfig(
        filename=DATA_DIR / "magiclab.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )


def install_exception_handler() -> None:
    def handler(exc_type, exc_value, exc_traceback) -> None:
        from app.services.access_service import AccessDenied
        if isinstance(exc_value, AccessDenied):
            QMessageBox.warning(None, 'Доступ ограничен', str(exc_value))
            return
        logging.critical("Необработанная ошибка", exc_info=(exc_type, exc_value, exc_traceback))
        QMessageBox.critical(
            None,
            "Ошибка",
            "Произошла внутренняя ошибка. Подробности сохранены в data/magiclab.log.",
        )

    sys.excepthook = handler


def create_application(argv: list[str]) -> QApplication:
    configure_windows_identity()
    QCoreApplication.setOrganizationName(ORGANIZATION_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    application = QApplication(argv)
    application.setWindowIcon(application_icon())
    # Offscreen-платформа Qt в Windows не перечисляет системные шрифты сама.
    if not QFontDatabase.families() and sys.platform == 'win32':
        font_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for filename in ('segoeui.ttf', 'segoeuib.ttf', 'segoeuii.ttf'):
            if (font_dir / filename).is_file():
                QFontDatabase.addApplicationFont(str(font_dir / filename))
    available_fonts = QFontDatabase.families()
    family = next((font for font in ('Segoe UI Variable', 'Segoe UI', 'Arial') if font in available_fonts), application.font().family())
    application.setFont(QFont(family, 10))
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: 'background', QPalette.ColorRole.WindowText: 'text',
        QPalette.ColorRole.Base: 'sidebar', QPalette.ColorRole.AlternateBase: 'surface',
        QPalette.ColorRole.Text: 'text', QPalette.ColorRole.Button: 'surface_alt',
        QPalette.ColorRole.ButtonText: 'text', QPalette.ColorRole.Highlight: 'purple',
        QPalette.ColorRole.HighlightedText: 'text', QPalette.ColorRole.ToolTipBase: 'surface_alt',
        QPalette.ColorRole.ToolTipText: 'text', QPalette.ColorRole.PlaceholderText: 'muted',
    }.items():
        palette.setColor(role, QColor(COLORS[color]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor('#737986'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor('#737986'))
    application.setPalette(palette)
    QLocale.setDefault(QLocale(QLocale.Language.Russian, QLocale.Country.Russia))
    translator = QTranslator(application)
    if not translator.load("qtbase_ru", str(RESOURCE_DIR / 'translations')):
        translator.load("qtbase_ru", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    application.installTranslator(translator)
    application.ru_translator = translator
    application.setStyle("Fusion")
    stylesheet = APP_STYLESHEET.replace('"Segoe UI Variable", "Segoe UI", Arial', f'"{family}"')
    application.setStyleSheet(stylesheet.replace('@ICONS@', (RESOURCE_DIR / 'icons').as_posix()))
    return application


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke-test", action="store_true")
    arguments, qt_arguments = parser.parse_known_args(argv or sys.argv[1:])
    app = create_application([sys.argv[0], *qt_arguments])
    try:
        configure_logging()
    except OSError:
        QMessageBox.critical(None, "Нет доступа к папке", "Переместите программу в папку с правом записи, например в Документы.")
        return 1
    install_exception_handler()
    if not arguments.smoke_test:
        app.database_lock = QLockFile(str(DATA_DIR / 'magiclab.lock'))
        if not app.database_lock.tryLock(100):
            QMessageBox.information(None, APP_NAME, "Программа уже запущена для этой базы данных.")
            return 0
    # Проверочный режим никогда не открывает рабочие данные без авторизации.
    database = Database('sqlite:///:memory:' if arguments.smoke_test else None)
    try:
        database.create_schema()
        database.seed_demo_services()
    except Exception:
        logging.exception('Ошибка открытия или миграции БД')
        database.dispose()
        QMessageBox.critical(None, 'Не удалось открыть базу',
            'Не удалось проверить или обновить базу данных. Рабочие разделы не открыты.\n'
            'Проверьте права записи и журнал data/magiclab.log. Перед обновлением существующей схемы '
            'программа создаёт копию before_roles в папке backups. Не удаляйте базу и резервные копии.')
        return 1

    if arguments.smoke_test:
        with database.session() as session:
            user = AuthService(session).create_admin('smoke-owner', 'temporary-smoke-password', 'Проверка приложения')
            session.commit()
            database.sign_in(user)
        window = MainWindow(database, user_id=user.id)
        window.refresh_all()
        window.show()
        QTimer.singleShot(1200, app.quit)
        result = app.exec()
        database.dispose()
        return result

    with database.session() as session:
        has_users = AuthService(session).has_users()
    auth_dialog = LoginDialog(database) if has_users else FirstRunDialog(database)
    if auth_dialog.exec() != QDialog.DialogCode.Accepted:
        database.dispose()
        return 0
    window = MainWindow(database, auth_dialog.user_id)
    window.show()
    result = app.exec()
    database.dispose()
    return result


if __name__ == "__main__":
    raise SystemExit(run())
