"""Копирует локальные ресурсы и сведения о зависимостях при сборке."""
from pathlib import Path
import importlib.metadata
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def prepare():
    from tools.build_icon import build_icon
    from PySide6.QtCore import QLibraryInfo
    build_icon(ROOT / 'app' / 'resources' / 'images' / 'logo.png',
               ROOT / 'app' / 'resources' / 'icons' / 'magiclab.ico')
    destination = ROOT / 'app' / 'resources' / 'translations'
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / 'qtbase_ru.qm'
    shutil.copy2(source, destination / source.name)

def finalize(release=None):
    release = Path(release or ROOT / 'dist' / 'MagicLabManager').resolve()
    if not (release / 'MagicLabManager.exe').is_file():
        raise ValueError('Финализация разрешена только для собранной папки MagicLabManager')
    # Qt 6.11 использует ICU API Windows. PyInstaller может подобрать из PATH
    # несовместимую стороннюю ICU с версионными именами экспортов (например Poppler).
    # В Windows 10/11 нужна системная DLL, а не копия из инструментов сборки.
    for filename in ('icuuc.dll', 'icudt78.dll'):
        collected = release / '_internal' / filename
        if collected.is_file():
            collected.unlink()
    for name in ('data', 'backups', 'exports', 'licenses'):
        (release / name).mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'README.md', release / 'README.md')
    # В docs хранятся и рабочие инструменты подготовки отчёта (включая офисный
    # runtime). Для переносимого приложения нужны материалы, а не эти окружения.
    shutil.copytree(ROOT / 'docs', release / 'docs', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('report_work', 'presentation_work', '__pycache__', '*.log', '*.lock'))
    for package in ('PySide6', 'PySide6_Essentials', 'shiboken6', 'SQLAlchemy', 'greenlet'):
        distribution = importlib.metadata.distribution(package)
        folder = release / 'licenses' / package
        folder.mkdir(parents=True, exist_ok=True)
        for file in distribution.files or ():
            path = Path(str(file))
            if path.name == 'METADATA' or 'licenses' in path.parts or 'LICENSE' in path.name.upper():
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    shutil.copy2(source, folder / source.name)
    for filename in ('LICENSE.txt', 'LICENSE'):
        source = Path(sys.base_prefix) / filename
        if source.is_file():
            shutil.copy2(source, release / 'licenses' / 'Python-LICENSE.txt')
            break

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--finalize', action='store_true')
    parser.add_argument('--release-dir', type=Path)
    args = parser.parse_args()
    if args.finalize:
        finalize(args.release_dir)
    else:
        prepare()
