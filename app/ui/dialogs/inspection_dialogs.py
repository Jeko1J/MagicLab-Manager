from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QLabel, QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QCheckBox, QPushButton, QTableWidget,
    QHeaderView, QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QDialogButtonBox,
    QScrollArea, QButtonGroup, QToolButton)

from app.inspection_catalog import VIEWS, BODY_ELEMENTS, DAMAGE_TYPES, SEVERITIES, CONDITIONS
from app.inspection_geometry import element_at, place_mark, position_matches, project_marks
from app.models import UserRole
from app.services.access_service import require_database, can
from app.services.inspection_service import InspectionService, load_photo
from app.ui.inspection_canvas import InspectionCanvas
from app.ui.widgets import ErrorLabel, configure_table, table_item, set_empty_text, fit_to_screen, format_datetime


def combo(catalog):
    field = QComboBox()
    for key, label in catalog.items():
        field.addItem(label, key)
    return field


class DamageDialog(QDialog):
    def __init__(self, values, editable=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Замечание к ЛКП')
        self.resize(890, 500)
        self.editable = editable
        self.values = place_mark(values)
        self.values['position_adjusted'] = values.get('position_adjusted', False) or any(
            self.values[key] != values[key] for key in ('view', 'normalized_x', 'normalized_y'))
        self.photo_files = []
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        columns = QHBoxLayout()
        columns.setSpacing(20)
        fields = QVBoxLayout()
        form = QFormLayout()
        form.setSpacing(10)
        self.body = combo(BODY_ELEMENTS)
        self.kind = combo(DAMAGE_TYPES)
        self.severity = combo(SEVERITIES)
        for field, key in ((self.body, 'body_element'), (self.kind, 'damage_type'), (self.severity, 'severity')):
            field.setCurrentIndex(max(0, field.findData(values.get(key))))
            field.setEnabled(editable)
        self.comment = QPlainTextEdit(values.get('comment', ''))
        self.comment.setMaximumHeight(110)
        self.comment.setReadOnly(not editable)
        self.thickness = QSpinBox()
        self.thickness.setRange(-1, 5000)
        self.thickness.setSpecialValueText('Не измерена')
        self.thickness.setSuffix(' мкм')
        self.thickness.setValue(values.get('paint_thickness_um') if values.get('paint_thickness_um') is not None else -1)
        self.thickness.setEnabled(editable)
        for label, field in (('Элемент кузова', self.body), ('Вид дефекта', self.kind), ('Степень', self.severity),
                             ('Толщина ЛКП', self.thickness), ('Комментарий', self.comment)):
            form.addRow(label, field)
        fields.addLayout(form)
        self.photo_note = QLabel('Новые фотографии не выбраны')
        self.photo_note.setWordWrap(True)
        add_photo = QPushButton('Прикрепить фотографии…')
        add_photo.clicked.connect(self.select_photos)
        add_photo.setVisible(editable)
        fields.addWidget(add_photo)
        fields.addWidget(self.photo_note)
        fields.addStretch()
        preview_layout = QVBoxLayout()
        self.position_title = QLabel()
        self.position_title.setWordWrap(True)
        preview_layout.addWidget(self.position_title)
        self.preview = InspectionCanvas()
        self.preview.editable = editable
        self.preview.setMinimumSize(330, 230)
        self.preview.point_clicked.connect(self.move_point)
        preview_layout.addWidget(self.preview, 1)
        self.position_note = QLabel()
        self.position_note.setObjectName('muted')
        self.position_note.setWordWrap(True)
        preview_layout.addWidget(self.position_note)
        columns.addLayout(fields, 1)
        columns.addLayout(preview_layout, 1)
        root.addLayout(columns, 1)
        self.error = ErrorLabel()
        root.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel if editable else QDialogButtonBox.StandardButton.Close)
        if editable:
            save = buttons.addButton('Сохранить', QDialogButtonBox.ButtonRole.AcceptRole)
            save.setObjectName('primary')
            save.clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.body.currentIndexChanged.connect(self.body_changed)
        self.severity.currentIndexChanged.connect(self.refresh_preview)
        self.refresh_preview()
        fit_to_screen(self)

    def refresh_preview(self, *_args):
        values = {**self.values, 'id': 0, 'body_element': self.body.currentData(),
                  'damage_type': self.kind.currentData(), 'severity': self.severity.currentData(),
                  'comment': self.comment.toPlainText(),
                  'paint_thickness_um': None if self.thickness.value() == -1 else self.thickness.value()}
        self.preview.set_view(values['view'], [values])
        self.position_title.setText(f"{VIEWS[values['view']]} · {BODY_ELEMENTS[values['body_element']]}")
        self.position_note.setText('Точка привязана к выбранной детали. Нажмите внутри этой детали, чтобы уточнить место.'
            if self.editable else 'Положение показано на схеме выбранной детали.')
        if self.values.get('position_adjusted'):
            self.position_note.setText('Положение подобрано по выбранной детали и пока ориентировочное; '
                + ('уточните его на схеме перед сохранением.' if self.editable else 'попросите администратора уточнить его.'))

    def body_changed(self, *_args):
        previous = self.values
        self.values = place_mark({**previous, 'body_element': self.body.currentData()})
        self.values['position_adjusted'] = any(self.values[key] != previous[key]
            for key in ('view', 'normalized_x', 'normalized_y'))
        self.error.clear()
        self.refresh_preview()

    def move_point(self, x, y):
        if not self.editable:
            return
        if not position_matches(self.values['view'], self.body.currentData(), x, y):
            self.error.setText(f'Выберите точку внутри детали «{self.body.currentText()}» или измените элемент кузова.')
            return
        self.values.update(normalized_x=x, normalized_y=y, position_adjusted=False)
        self.error.clear()
        self.refresh_preview()

    def select_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Фотографии дефекта', '', 'Фотографии (*.jpg *.jpeg *.png)')
        if paths:
            self.photo_files = paths
            self.photo_note.setText(f'Будут скопированы после сохранения: {len(paths)}')

    def save(self):
        values = {**self.values, 'body_element': self.body.currentData(), 'damage_type': self.kind.currentData(),
            'severity': self.severity.currentData(), 'comment': self.comment.toPlainText(),
            'paint_thickness_um': None if self.thickness.value() == -1 else self.thickness.value()}
        try:
            self.values = place_mark(InspectionService.validate_mark(values))
            for path in self.photo_files:
                load_photo(Path(path))
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class PhotoViewer(QDialog):
    def __init__(self, image, caption, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Фотография осмотра')
        self.resize(980, 680)
        self.image = image
        root = QVBoxLayout(self)
        note = QLabel(caption or 'Без подписи')
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        root.addWidget(note)
        actions = QHBoxLayout()
        fit = QPushButton('Вписать')
        actual = QPushButton('100%')
        fit.clicked.connect(self.fit_image)
        actual.clicked.connect(lambda: self.set_image(self.image))
        actions.addWidget(fit)
        actions.addWidget(actual)
        actions.addStretch()
        root.addLayout(actions)
        self.scroll = QScrollArea()
        self.label = QLabel()
        self.scroll.setWidget(self.label)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.scroll, 1)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        root.addWidget(close)
        fit_to_screen(self)
        self.set_image(self.image.scaled(900, 500, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def set_image(self, image):
        self.label.setPixmap(QPixmap.fromImage(image))
        self.label.resize(image.size())

    def fit_image(self):
        self.set_image(self.image.scaled(self.scroll.viewport().size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


class InspectionPanel(QWidget):
    data_changed = Signal()
    print_requested = Signal()
    close_requested = Signal()

    def __init__(self, database, order_id, parent=None):
        super().__init__(parent)
        self.database, self.order_id = database, order_id
        actor = require_database(database, 'inspection_view')
        self.editable = can(actor, 'inspection_edit')
        self.is_master = actor.role == UserRole.MASTER
        self.selected_id = None
        self.view = 'TOP'
        self.snapshot = None
        self._initial = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(6)
        self.note = QLabel()
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        split = self.splitter = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName('inspectionSplit')
        split.setChildrenCollapsible(False)
        split.setHandleWidth(6)
        split.setStyleSheet('QSplitter#inspectionSplit::handle { background: #111318; width: 6px; }')
        left, right = QWidget(), QWidget()
        left_layout, right_layout = QVBoxLayout(left), QVBoxLayout(right)
        for layout in (left_layout, right_layout):
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
        left_layout.setContentsMargins(0, 0, 8, 0)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.view_buttons = {}
        views = QHBoxLayout()
        group = QButtonGroup(self)
        for key, label in VIEWS.items():
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setChecked(key == 'TOP')
            button.clicked.connect(lambda _checked=False, value=key: self.change_view(value))
            group.addButton(button)
            self.view_buttons[key] = button
            views.addWidget(button)
        left_layout.addLayout(views)
        self.canvas = InspectionCanvas()
        self.canvas.setMaximumHeight(440)
        self.canvas.editable = self.editable
        self.canvas.point_clicked.connect(self.add_mark)
        self.canvas.marker_clicked.connect(self.marker_clicked)
        left_layout.addWidget(self.canvas, 1)
        hint = QLabel('Нажмите на деталь кузова, чтобы добавить дефект. Элемент определяется по схеме. Повторное нажатие на маркер — открыть.' if self.editable else 'Выберите маркер или строку для просмотра. Исходные замечания изменяет администратор.')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        left_layout.addWidget(hint)
        legend = QLabel('● Серо-синий — замечание / небольшой дефект\n● Янтарный — средний    ● Красный — существенный')
        legend.setObjectName('muted')
        legend.setWordWrap(True)
        left_layout.addWidget(legend)
        left_layout.addStretch()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(('№', 'Элемент', 'Дефект', 'Степень', 'мкм', 'Комментарий', 'Фото'))
        configure_table(self.table)
        self.table.setMinimumHeight(224)
        self.table.horizontalHeader().setMinimumSectionSize(28)
        for column, width in ((0, 34), (1, 138), (2, 126), (3, 112), (4, 48), (6, 60)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self.select_row)
        self.table.doubleClicked.connect(lambda _: self.edit_mark())
        set_empty_text(self.table, 'Замечаний нет. Выберите место на схеме.' if self.editable else 'Замечаний пока нет.')
        right_layout.addWidget(self.table, 3)
        actions = QHBoxLayout()
        self.edit_button = QPushButton('Изменить' if self.editable else 'Просмотреть')
        self.delete_button = QPushButton('Удалить замечание')
        self.edit_button.clicked.connect(self.edit_mark)
        self.delete_button.clicked.connect(self.delete_mark)
        self.delete_button.setVisible(self.editable)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch()
        right_layout.addLayout(actions)
        self.detail = QLabel('Выберите замечание для подробностей')
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        self.detail.setMaximumHeight(68)
        right_layout.addWidget(self.detail)
        photo_actions = QHBoxLayout()
        self.photo_filter = QCheckBox('Только выбранное')
        self.photo_filter.setToolTip('Показать только фотографии выбранного замечания')
        self.photo_filter.toggled.connect(self.load_photos)
        photo_actions.addWidget(self.photo_filter)
        photo_actions.addStretch()
        self.add_photo_button = QPushButton('Добавить фото')
        self.add_photo_button.setVisible(self.editable)
        self.add_photo_button.clicked.connect(self.add_photo)
        photo_actions.addWidget(self.add_photo_button)
        right_layout.addLayout(photo_actions)
        self.photos = QListWidget()
        self.photos.setFlow(QListWidget.Flow.LeftToRight)
        self.photos.setIconSize(QSize(78, 50))
        self.photos.setFixedHeight(84)
        self.photos.setSpacing(5)
        self.photos.setStyleSheet('QListWidget { padding: 4px; }')
        self.photos.itemDoubleClicked.connect(lambda _: self.open_photo())
        right_layout.addWidget(self.photos)
        photo_buttons = photo_actions
        self.open_photo_button = QPushButton('Открыть')
        self.open_photo_button.setToolTip('Открыть фотографию, включая размер 100%')
        self.delete_photo_button = QPushButton('Удалить')
        self.delete_photo_button.setToolTip('Удалить выбранную фотографию')
        self.caption_button = QPushButton('Подпись')
        self.caption_button.setToolTip('Изменить подпись и привязку фотографии')
        self.caption_button.setVisible(self.editable)
        self.caption_button.clicked.connect(self.edit_photo)
        self.open_photo_button.clicked.connect(self.open_photo)
        self.delete_photo_button.clicked.connect(self.delete_photo)
        self.delete_photo_button.setVisible(self.editable)
        photo_buttons.addWidget(self.open_photo_button)
        photo_buttons.addWidget(self.caption_button)
        photo_buttons.addWidget(self.delete_photo_button)
        photo_buttons.addStretch()
        self.photos.itemSelectionChanged.connect(self.photo_selection)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([420, 700])
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)
        details = QHBoxLayout()
        self.condition = QComboBox()
        self.condition.addItems(CONDITIONS)
        self.condition.setEnabled(self.editable)
        details.addWidget(QLabel('Общее состояние'))
        details.addWidget(self.condition)
        self.customer_ack = QCheckBox('Клиент с состоянием ознакомлен')
        self.customer_ack.setEnabled(self.editable)
        details.addWidget(self.customer_ack)
        details.addStretch()
        root.addLayout(details)
        self.comment = QPlainTextEdit()
        self.comment.setPlaceholderText('Общий комментарий и ограничения перед полировкой')
        self.comment.setStyleSheet('QPlainTextEdit { min-height: 42px; max-height: 42px; }')
        self.comment.setFixedHeight(52)
        self.comment.setReadOnly(not self.editable)
        root.addWidget(self.comment)
        self.review_note = QLabel()
        self.review_note.setWordWrap(True)
        root.addWidget(self.review_note)
        self.error = ErrorLabel()
        root.addWidget(self.error)
        footer = QHBoxLayout()
        self.save_button = QPushButton('Сохранить')
        self.save_button.setObjectName('primary')
        self.save_button.setVisible(self.editable)
        self.save_button.clicked.connect(self.save_details)
        self.review_button = QPushButton('С картой осмотра ознакомлен')
        self.review_button.setVisible(self.is_master)
        self.review_button.clicked.connect(self.review)
        self.print_button = QPushButton('Печать')
        self.print_button.setVisible(can(actor, 'inspection_print'))
        self.print_button.clicked.connect(self.print_requested)
        for button in (self.save_button, self.review_button, self.print_button):
            footer.addWidget(button)
        footer.addStretch()
        close = QPushButton('Закрыть')
        close.clicked.connect(self.close_requested)
        footer.addWidget(close)
        root.addLayout(footer)
        self.refresh(False)

    def general_values(self):
        return self.condition.currentText(), self.comment.toPlainText(), self.customer_ack.isChecked()

    def confirm_close(self):
        if not self.editable or self.general_values() == self._initial:
            return True
        answer = QMessageBox.question(self, 'Несохранённый комментарий', 'Сохранить общее состояние и комментарий?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        return self.save_details() if answer == QMessageBox.StandardButton.Save else True

    def refresh(self, preserve=True):
        pending = self.general_values() if self._initial and self.general_values() != self._initial and preserve else None
        with self.database.session() as session:
            self.snapshot = InspectionService(session).get(self.order_id)
        inspection = self.snapshot['inspection']
        self.marks = project_marks(inspection['marks']) if inspection else []
        self.photo_rows = inspection['photos'] if inspection else []
        self.note.setText(f"Первичный осмотр · {self.snapshot['number']} · {self.snapshot['vehicle']}" +
            (f" · {format_datetime(inspection['created_at'])}" if inspection else ' · Карта ещё не создана'))
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.marks))
        for row, mark in enumerate(self.marks):
            count = sum(photo['damage_mark_id'] == mark['id'] for photo in self.photo_rows)
            short_severity = {'INFO': 'Информация', 'MINOR': 'Незначит.', 'MEDIUM': 'Средний', 'MAJOR': 'Существенный'}
            values = (str(row + 1), BODY_ELEMENTS[mark['body_element']], DAMAGE_TYPES[mark['damage_type']],
                short_severity[mark['severity']], str(mark['paint_thickness_um']) if mark['paint_thickness_um'] is not None else '—', mark['comment'] or '—', str(count))
            for column, value in enumerate(values):
                self.table.setItem(row, column, table_item(value, mark['id'] if column == 0 else None))
            self.table.item(row, 3).setToolTip(SEVERITIES[mark['severity']])
            if mark['position_adjusted']:
                self.table.item(row, 1).setText(BODY_ELEMENTS[mark['body_element']] + ' *')
                self.table.item(row, 1).setToolTip('Старая точка не соответствует детали. Показано ориентировочное место; откройте замечание и уточните точку. Исходная запись не изменена.')
        self.table.blockSignals(False)
        self.condition.setCurrentText(inspection['general_condition'] or CONDITIONS[0] if inspection else CONDITIONS[0])
        self.comment.setPlainText(inspection['general_comment'] if inspection else '')
        self.customer_ack.setChecked(inspection['customer_acknowledged'] if inspection else False)
        self._initial = self.general_values()
        if pending:
            self.condition.setCurrentText(pending[0])
            self.comment.setPlainText(pending[1])
        reviewed = inspection and inspection['master_reviewed']
        self.review_note.setText(f"Ознакомлен: {inspection['reviewer_name']} · {format_datetime(inspection['master_reviewed_at'])}" if reviewed
            else 'Мастер ещё не отметил ознакомление с текущей картой.')
        self.review_button.setEnabled(bool(inspection) and not reviewed)
        self.print_button.setEnabled(bool(inspection))
        self.change_view(self.view)
        for row, mark in enumerate(self.marks):
            if mark['id'] == self.selected_id:
                self.table.selectRow(row)
                break
        else:
            self.selected_id = None
        self.select_row()
        self.load_photos()

    def change_view(self, view):
        self.view = view
        self.view_buttons[view].setChecked(True)
        self.canvas.set_view(view, self.marks)
        self.canvas.highlight(self.selected_id)

    def select_row(self):
        row = self.table.currentRow()
        self.selected_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 and self.table.item(row, 0) else None
        self.edit_button.setEnabled(self.selected_id is not None)
        self.delete_button.setEnabled(self.selected_id is not None)
        mark = next((m for m in self.marks if m['id'] == self.selected_id), None)
        if mark:
            if mark['view'] != self.view:
                self.change_view(mark['view'])
            self.detail.setText(f"{BODY_ELEMENTS[mark['body_element']]} · {DAMAGE_TYPES[mark['damage_type']]}\n{mark['comment'] or 'Комментарий не указан'}")
            if mark['position_adjusted']:
                refinement = 'уточните точку в замечании.' if self.editable else 'попросите администратора уточнить точку.'
                self.detail.setText(self.detail.text() + '\n* Положение ориентировочное — ' + refinement)
            self.detail.setToolTip(self.detail.text())
        else:
            self.detail.setText('Выберите замечание для подробностей')
        self.canvas.highlight(self.selected_id)
        self.load_photos()

    def marker_clicked(self, mark_id):
        repeated = self.selected_id == mark_id
        for row, mark in enumerate(self.marks):
            if mark['id'] == mark_id:
                self.table.selectRow(row)
                break
        if repeated:
            self.edit_mark()

    def _write(self, callback):
        try:
            with self.database.session() as session:
                try:
                    result = callback(InspectionService(session))
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            self.error.clear()
            self.refresh()
            self.data_changed.emit()
            return True, result
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return False, None

    def add_mark(self, x, y):
        body = element_at(self.view, x, y)
        if body is None:
            return
        values = {'view': self.view, 'normalized_x': x, 'normalized_y': y,
                  'body_element': body, 'damage_type': 'LIGHT_SCRATCH', 'severity': 'MINOR'}
        self._mark_dialog(values)

    def edit_mark(self):
        mark = next((m for m in self.marks if m['id'] == self.selected_id), None)
        if mark:
            self._mark_dialog(mark, mark['id'])

    def _mark_dialog(self, values, mark_id=None):
        dialog = DamageDialog(values, self.editable, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not self.editable:
            return
        def save(service):
            identifier = service.save_mark(self.order_id, dialog.values, mark_id)
            for path in dialog.photo_files:
                service.add_photo(self.order_id, path, '', identifier)
            return identifier
        ok, identifier = self._write(save)
        if ok:
            self.selected_id = identifier
            self.refresh()

    def delete_mark(self):
        if self.selected_id and QMessageBox.question(self, 'Удалить замечание',
            'Удалить замечание и все привязанные к нему фотографии? Действие будет записано в журнал.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._write(lambda service: service.delete_mark(self.order_id, self.selected_id))

    def save_details(self):
        ok, _ = self._write(lambda service: service.save_details(self.order_id, *self.general_values()))
        if ok:
            self.refresh(False)
            self.note.setText(self.note.text() + ' · Сохранено')
        return ok

    def review(self):
        self._write(lambda service: service.acknowledge_master(self.order_id))

    def load_photos(self):
        if not hasattr(self, 'photo_rows'):
            return
        previous = self.photos.currentItem().data(Qt.ItemDataRole.UserRole) if self.photos.currentItem() else None
        self.photos.clear()
        for photo in self.photo_rows:
            if self.photo_filter.isChecked() and photo['damage_mark_id'] != self.selected_id:
                continue
            number = next((i + 1 for i, m in enumerate(self.marks) if m['id'] == photo['damage_mark_id']), None)
            item = QListWidgetItem(f"№ {number}" if number else 'Общее фото')
            item.setData(Qt.ItemDataRole.UserRole, photo['id'])
            item.setToolTip(photo['caption'] or photo['original_filename'])
            try:
                with self.database.session() as session:
                    path = InspectionService(session).photo_path(self.order_id, photo['id'])
                image = load_photo(path)
                item.setIcon(QIcon(QPixmap.fromImage(image.scaled(88, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))))
            except (ValueError, OSError) as exc:
                item.setText('Фото недоступно')
                item.setToolTip(str(exc))
            self.photos.addItem(item)
            if photo['id'] == previous:
                self.photos.setCurrentItem(item)
        self.photo_selection()

    def photo_selection(self):
        enabled = self.photos.currentItem() is not None
        self.open_photo_button.setEnabled(enabled)
        self.delete_photo_button.setEnabled(enabled)
        self.caption_button.setEnabled(enabled)

    def add_photo(self, _checked=False, photo=None):
        paths = []
        if photo is None:
            paths, _ = QFileDialog.getOpenFileNames(self, 'Прикрепить фото осмотра', '', 'Фотографии (*.jpg *.jpeg *.png)')
        if photo is None and not paths:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Подпись и привязка фотографии')
        layout = QFormLayout(dialog)
        caption = QLineEdit()
        if photo:
            caption.setText(photo['caption'])
        caption.setMaxLength(1000)
        binding = QComboBox()
        binding.addItem('Общее фото осмотра', None)
        for index, mark in enumerate(self.marks, 1):
            binding.addItem(f"№ {index} · {BODY_ELEMENTS[mark['body_element']]}", mark['id'])
        binding.setCurrentIndex(max(0, binding.findData(photo['damage_mark_id'] if photo else self.selected_id)))
        layout.addRow('Подпись', caption)
        layout.addRow('Замечание', binding)
        layout.addRow(QLabel('Исходный файл не меняется' if photo else f'Файлов для копирования: {len(paths)}'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if photo:
                self._write(lambda service: service.update_photo(self.order_id, photo['id'], caption.text(), binding.currentData()))
            else:
                self._write(lambda service: [service.add_photo(self.order_id, path, caption.text(), binding.currentData()) for path in paths])

    def edit_photo(self):
        if self.photos.currentItem():
            identifier = self.photos.currentItem().data(Qt.ItemDataRole.UserRole)
            self.add_photo(photo=next(photo for photo in self.photo_rows if photo['id'] == identifier))

    def open_photo(self):
        item = self.photos.currentItem()
        if not item:
            return
        try:
            with self.database.session() as session:
                path = InspectionService(session).photo_path(self.order_id, item.data(Qt.ItemDataRole.UserRole))
                image = load_photo(path)
            photo = next(p for p in self.photo_rows if p['id'] == item.data(Qt.ItemDataRole.UserRole))
            PhotoViewer(image, photo['caption'], self).exec()
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))

    def delete_photo(self):
        item = self.photos.currentItem()
        if item and QMessageBox.question(self, 'Удалить фотографию', 'Удалить фотографию из карты и папки приложения?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            identifier = item.data(Qt.ItemDataRole.UserRole)
            self._write(lambda service: service.delete_photo(self.order_id, identifier))
