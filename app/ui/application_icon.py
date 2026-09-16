import ctypes
import logging
import sys

from PySide6.QtGui import QIcon

from app.config import RESOURCE_DIR

WINDOWS_APP_ID = 'MagicLab.Detailing.Manager'


def application_icon() -> QIcon:
    icon = QIcon(str(RESOURCE_DIR / 'icons' / 'magiclab.ico'))
    if icon.isNull():
        # Запуск из исходников возможен и до подготовки ICO при сборке.
        icon = QIcon(str(RESOURCE_DIR / 'images' / 'logo.png'))
    return icon


def configure_windows_identity() -> None:
    """Вызывать до QApplication, чтобы Windows группировала окна отдельно."""
    if sys.platform != 'win32':
        return
    try:
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        hr = setter(WINDOWS_APP_ID)
        if hr != 0:
            logging.getLogger(__name__).warning('AppUserModelID: HRESULT %s', hr)
    except (OSError, AttributeError):
        logging.getLogger(__name__).warning('AppUserModelID недоступен', exc_info=True)
