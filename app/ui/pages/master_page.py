from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget

from app.models import ALLOWED_STATUS_TRANSITIONS, ORDER_STATUS_LABELS, OrderStatus
from app.services.access_service import require_database
from app.services.audit_service import record_event
from app.services.master_order_service import MasterOrderService
from app.ui.pages.base import Page
from app.ui.widgets import configure_table, table_item, status_item, format_datetime, format_duration, set_empty_text, ErrorLabel, fit_to_screen


class MasterPage(Page):
    open_order = Signal(int)

    def __init__(self, database, parent=None):
        require_database(database, 'master_orders')
        super().__init__(database, 'Мои заказы', parent)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер заказа, автомобиль или госномер')
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(540)
        self.mode = QComboBox()
        self.mode.addItem('Текущие заказы', True)
        self.mode.addItem('Вся моя история', False)
        self.header.addWidget(self.search, 1)
        self.header.addWidget(self.mode)
        self.root.addWidget(QLabel('Только назначенные вам работы. Время готовности рассчитано по длительности услуг, без перерывов.'))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(('Заказ', 'Запись', 'Автомобиль', 'Услуги', 'Ориентировочно готов', 'Статус'))
        configure_table(self.table, sortable=True)
        for col, width in ((0, 145), (1, 150), (4, 188), (5, 120)):
            self.table.setColumnWidth(col, width)
        for col in (2, 3):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self.open_selected)
        self.root.addWidget(self.table, 1)
        open_button = QPushButton('Открыть заказ')
        open_button.clicked.connect(self.open_selected)
        self.header.addWidget(open_button)
        set_empty_text(self.table, 'Назначенных заказов не найдено. Уточните назначение у администратора или измените фильтр.')
        self.search.textChanged.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.refresh)

    def open_selected(self):
        item = self.table.item(self.table.currentRow(), 0)
        if item:
            self.open_order.emit(item.data(Qt.ItemDataRole.UserRole))

    def refresh(self):
        with self.database.session() as session:
            orders = MasterOrderService(session).list_orders(self.search.text(), self.mode.currentData())
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            cells = (table_item(order.public_number, order.id), table_item(format_datetime(order.scheduled_at), sort_value=order.scheduled_at.timestamp()),
                     table_item(f'{order.vehicle}, {order.license_plate}'), table_item(', '.join(name for name, _ in order.services)),
                     table_item(format_datetime(order.expected_finish), sort_value=order.expected_finish.timestamp()), status_item(order.status))
            for col, item in enumerate(cells):
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)


class MasterOrderDialog(QDialog):
    def __init__(self, database, order_id, parent=None):
        require_database(database, 'master_orders')
        super().__init__(parent)
        self.database, self.order_id = database, order_id
        self.changed = False
        self.setWindowTitle('Работы по заказу')
        self.resize(1240, 700)
        self.setMinimumSize(700, 510)
        outer = QVBoxLayout(self)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        order_page = QWidget()
        self.tabs.addTab(order_page, 'Работы по заказу')
        root = QVBoxLayout(order_page)
        root.setContentsMargins(20, 16, 20, 16)
        self.title = QLabel()
        self.title.setObjectName('pageTitle')
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        self.comment = QPlainTextEdit()
        self.comment.setReadOnly(True)
        self.comment.setMaximumHeight(100)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(('Услуга', 'Продолжительность'))
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 170)
        self.status_comment = QLineEdit()
        self.status_comment.setPlaceholderText('Комментарий к смене статуса — при необходимости')
        self.error = ErrorLabel()
        for widget in (self.title, self.summary, QLabel('Комментарий к работам'), self.comment, self.table, self.status_comment, self.error):
            root.addWidget(widget)
        actions = QHBoxLayout()
        self.start = QPushButton('В работу')
        self.ready = QPushButton('Готов')
        self.start.setObjectName('primary')
        self.ready.setObjectName('primary')
        self.start.clicked.connect(lambda: self.change_status(OrderStatus.IN_PROGRESS))
        self.ready.clicked.connect(lambda: self.change_status(OrderStatus.READY))
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        actions.addWidget(self.start)
        actions.addWidget(self.ready)
        actions.addStretch()
        actions.addWidget(close)
        root.addLayout(actions)
        self.load_data()
        from app.ui.dialogs.inspection_dialogs import InspectionPanel
        self.inspection_panel = InspectionPanel(database, order_id, self)
        self.tabs.addTab(self.inspection_panel, 'Осмотр ЛКП')
        self.inspection_panel.close_requested.connect(self.accept)
        record_event(database, 'Просмотр заказа мастером', 'Открыта рабочая карточка без финансов и контактов', self.number)
        fit_to_screen(self)

    def load_data(self):
        with self.database.session() as session:
            order = MasterOrderService(session).by_id(self.order_id)
        self.number = order.public_number
        self.title.setText(f'Заказ {order.public_number}')
        self.summary.setText(f'{order.vehicle} · {order.license_plate} · {order.color or "Цвет не указан"}\n'
            f'Запись: {format_datetime(order.scheduled_at)}   ·   {ORDER_STATUS_LABELS[order.status]}\n'
            f'Ориентировочно готов: {format_datetime(order.expected_finish)} (без перерывов)')
        self.comment.setPlainText(order.comment or 'Комментарий не указан')
        self.table.setRowCount(len(order.services))
        for row, (name, duration) in enumerate(order.services):
            self.table.setItem(row, 0, table_item(name))
            self.table.setItem(row, 1, table_item(format_duration(duration)))
        allowed = ALLOWED_STATUS_TRANSITIONS[order.status]
        self.start.setVisible(OrderStatus.IN_PROGRESS in allowed)
        self.start.setText('Вернуть в работу' if order.status == OrderStatus.READY else 'В работу')
        self.ready.setVisible(OrderStatus.READY in allowed)
        self.status_comment.setVisible(bool(allowed & {OrderStatus.IN_PROGRESS, OrderStatus.READY}))

    def change_status(self, status):
        try:
            with self.database.session() as session:
                MasterOrderService(session).change_status(self.order_id, status, self.status_comment.text())
                session.commit()
            self.changed = True
            self.status_comment.clear()
            self.error.clear()
            self.load_data()
        except ValueError as exc:
            self.error.setText(str(exc))
