from __future__ import annotations

COLORS = {
    "background": "#111318",
    "sidebar": "#17191F",
    "surface": "#1D2027",
    "surface_alt": "#242831",
    "border": "#323743",
    "text": "#F2F3F5",
    "muted": "#A6ACB8",
    "purple": "#8954D1",
    "blue": "#3E78D8",
    "success": "#4A9D68",
    "warning": "#C6923E",
    "error": "#CF5B5B",
}

APP_STYLESHEET = """
* {
    font-family: "Segoe UI Variable", "Segoe UI", Arial;
    font-size: 13px;
    color: #F2F3F5;
}
QWidget { background: #111318; }
QMainWindow, QDialog { background: #111318; }
QLabel { background: transparent; }
QLabel#pageTitle { font-size: 19px; font-weight: 600; }
QLabel#sectionTitle { font-size: 14px; font-weight: 600; }
QLabel#muted, QLabel.muted { color: #A6ACB8; }
QLabel#error { color: #F18F8F; padding: 2px 0; }
QLabel#metricValue { font-size: 21px; font-weight: 600; }
QLabel#metricCaption { color: #A6ACB8; }
QLabel#monogram { background:#8954D1; color:white; font-weight:700; font-size:15px; border-radius:6px; }
QLabel#brandText { font-size:14px; font-weight:600; }
QFrame#separator { background:#323743; }
QFrame#sidebar { background: #17191F; border-right: 1px solid #323743; }
QFrame#panel, QGroupBox {
    background: #1D2027;
    border: 1px solid #323743;
    border-radius: 3px;
}
QFrame#metric { background: transparent; border-top: 1px solid #323743; }
QGroupBox { background: transparent; border: none; border-top: 1px solid #323743; border-radius: 0; margin-top: 14px; padding: 16px 0 12px 0; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 0; padding: 0 8px 0 0; color: #F2F3F5; }
QPushButton {
    background: #242831;
    border: 1px solid #3B414F;
    border-radius: 3px;
    padding: 0 12px;
    min-height: 30px;
}
QPushButton:hover { background: #2C313C; border-color: #555E70; }
QPushButton:pressed { background: #1D2027; }
QPushButton:focus { border: 1px solid #8954D1; }
QPushButton:disabled { color: #737986; background: #1B1E25; border-color: #292D36; }
QPushButton#primary { background: #8954D1; border-color: #8954D1; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #9864DA; }
QPushButton#primary:pressed { background: #7443B8; }
QPushButton#danger { color: #F2F3F5; border-color: #8E4141; background: #512D31; }
QPushButton#danger:hover { background: #68353A; }
QPushButton#nav {
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    min-height: 38px;
    padding: 0 14px;
    text-align: left;
    color: #C5CAD3;
}
QPushButton#nav:hover { background: #20232B; color: white; }
QPushButton#nav:checked { background: #242831; border-left-color: #8954D1; color: white; font-weight: 600; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QDateEdit, QDateTimeEdit, QSpinBox, QDoubleSpinBox {
    background: #17191F;
    border: 1px solid #3B414F;
    border-radius: 3px;
    padding: 4px 8px;
    min-height: 22px;
    selection-background-color: #8954D1;
}
QTextEdit, QPlainTextEdit { min-height: 58px; }
QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QDateEdit:hover, QDateTimeEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #555E70; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #8954D1; }
QLineEdit:disabled, QComboBox:disabled { color: #737986; background: #1B1E25; }
QLineEdit[invalid="true"], QComboBox[invalid="true"], QDoubleSpinBox[invalid="true"], QTableWidget[invalid="true"] { border: 1px solid #F18F8F; }
QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down { border: none; width: 26px; }
QComboBox::down-arrow, QDateEdit::down-arrow, QDateTimeEdit::down-arrow { image: url(@ICONS@/chevron-down.svg); width: 10px; height: 10px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { width: 18px; border: none; }
QSpinBox::down-button, QDoubleSpinBox::down-button { width: 18px; border: none; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@ICONS@/chevron-up.svg); width: 9px; height: 9px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@ICONS@/chevron-down.svg); width: 9px; height: 9px; }
QComboBox QAbstractItemView { background: #242831; border: 1px solid #3B414F; selection-background-color: #8954D1; }
QTableWidget, QTableView, QListWidget {
    background: #17191F;
    alternate-background-color: #17191F;
    border: 1px solid #323743;
    border-radius: 0;
    gridline-color: #2B303A;
    selection-background-color: #4F386B;
    selection-color: #FFFFFF;
}
QHeaderView::section {
    background: #242831;
    color: #C9CED8;
    border: none;
    border-right: 1px solid #323743;
    border-bottom: 1px solid #323743;
    padding: 7px 8px;
    font-weight: 600;
}
QTableWidget::item { padding: 5px; border-bottom: 1px solid #282C35; }
QTableWidget::item:hover { background: #20242C; }
QScrollBar:vertical { background: #17191F; width: 11px; margin: 0; }
QScrollBar::handle:vertical { background: #3B414F; min-height: 28px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #555E70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #17191F; height: 11px; }
QScrollBar::handle:horizontal { background: #3B414F; min-width: 28px; border-radius: 5px; }
QCalendarWidget QWidget { alternate-background-color: #1D2027; }
QCalendarWidget QAbstractItemView { background: #17191F; selection-background-color: #8954D1; }
QCalendarWidget QToolButton { color: #F2F3F5; background: #242831; border: none; min-height: 30px; padding: 0 6px; }
QCalendarWidget QToolButton:hover { background: #323743; }
QCalendarWidget QToolButton::menu-indicator { image: none; }
QToolTip { background: #242831; color: #F2F3F5; border: 1px solid #555E70; padding: 5px; }
QStatusBar { background: #17191F; border-top: 1px solid #323743; color: #A6ACB8; }
QMenu { background: #242831; border: 1px solid #3B414F; padding: 4px; }
QMenu::item { padding: 7px 24px 7px 12px; border-radius: 4px; }
QMenu::item:selected { background: #8954D1; }
QSplitter::handle { background: #323743; width: 1px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator, QTableWidget::indicator { width: 16px; height: 16px; border: 1px solid #697384; border-radius: 2px; background: #17191F; }
QCheckBox::indicator:checked, QTableWidget::indicator:checked { image: url(@ICONS@/check.svg); background: #8954D1; border-color: #8954D1; }
QTabWidget::pane { border: none; border-top: 1px solid #323743; }
QTabBar::tab { color: #C9CED8; background: #17191F; padding: 8px 18px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #FFFFFF; background: #242831; border-bottom: 2px solid #8954D1; }
QToolButton { color: #C9CED8; background: #242831; border: 1px solid #3B414F; padding: 6px; }
QToolButton:checked { color: #FFFFFF; background: #4F386B; border-color: #8954D1; }
"""

STATUS_COLORS = {
    "NEW": "#B7BDC7",
    "BOOKED": "#B998E6",
    "IN_PROGRESS": "#E1B666",
    "READY": "#80C698",
    "COMPLETED": "#A6ACB8",
    "CANCELLED": "#ED9696",
}
