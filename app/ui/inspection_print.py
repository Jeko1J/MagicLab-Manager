"""Ресурсы печатной формы встроены в QTextDocument и не зависят от исходной флешки."""
from html import escape

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QTextDocument

from app.inspection_catalog import VIEWS, BODY_ELEMENTS, DAMAGE_TYPES, SEVERITIES
from app.inspection_geometry import project_marks
from app.services.inspection_service import InspectionService, load_photo
from app.services.access_service import require
from app.ui.inspection_canvas import render_scheme
from app.ui.widgets import format_datetime


def inspection_print_parts(session, order_id):
    require(session, 'inspection_print')
    service = InspectionService(session)
    snapshot = service.get(order_id)
    inspection = snapshot['inspection']
    if not inspection:
        return '', {}
    inspection = {**inspection, 'marks': project_marks(inspection['marks'])}
    resources = {}
    headline = f"Карта первичного осмотра ЛКП · {escape(snapshot['number'])}"
    parts = [f"<h2 style='page-break-before:always'>{headline}</h2><p>{escape(snapshot['vehicle'])}<br>"
             f"Дата осмотра: {format_datetime(inspection['created_at'])}<br>"
             f"Общее состояние: {escape(inspection['general_condition'] or 'Не указано')}</p>"]
    cells = []
    for view, label in VIEWS.items():
        key = f'inspection://scheme/{view}'
        resources[key] = render_scheme(view, inspection['marks'])
        cells.append(f"<td width='50%'><b>{label}</b><br><img src='{key}' width='260' height='149'></td>")
    parts.append("<table width='100%' cellpadding='4'>")
    for index in range(0, len(cells), 2):
        parts.append('<tr>' + ''.join(cells[index:index + 2]) + ('<td></td>' if index + 1 == len(cells) else '') + '</tr>')
    parts.append('</table>')
    if any(mark['position_adjusted'] for mark in inspection['marks']):
        parts.append('<p>* У отмеченных замечаний старая точка не соответствовала элементу. '
                     'На схеме показано ориентировочное положение по названию детали, требующее уточнения.</p>')
    parts.append(f"<h2 style='page-break-before:always'>Замечания к осмотру · {escape(snapshot['number'])}</h2>")
    parts.append("<table width='100%' cellpadding='4'><thead><tr><th>№</th><th>Вид / элемент</th><th>Дефект / степень</th><th>ЛКП, мкм</th><th>Комментарий</th></tr></thead>")
    for number, mark in enumerate(inspection['marks'], 1):
        adjusted = ' *' if mark['position_adjusted'] else ''
        parts.append(f"<tr><td>{number}</td><td>{VIEWS[mark['view']]}<br>{BODY_ELEMENTS[mark['body_element']]}{adjusted}</td>"
            f"<td>{DAMAGE_TYPES[mark['damage_type']]}<br>{SEVERITIES[mark['severity']]}</td>"
            f"<td>{mark['paint_thickness_um'] if mark['paint_thickness_um'] is not None else '—'}</td>"
            f"<td>{escape(mark['comment'] or '—').replace(chr(10), '<br>')}</td></tr>")
    if not inspection['marks']:
        parts.append("<tr><td colspan='5'>Замечания не внесены.</td></tr>")
    parts.append('</table><h2>Общий комментарий и ограничения</h2>')
    parts.append(f"<p>{escape(inspection['general_comment'] or 'Не указаны').replace(chr(10), '<br>')}</p>")
    checked = 'Да' if inspection['customer_acknowledged'] else 'Не отмечено'
    parts.append(f'<p>Клиент с зафиксированным состоянием ознакомлен: {checked}</p>')
    if inspection['customer_acknowledged_at']:
        parts.append(f"<p>Дата отметки сотрудником: {format_datetime(inspection['customer_acknowledged_at'])}</p>")
    if inspection['master_reviewed']:
        parts.append(f"<p>Мастер ознакомлен: {escape(inspection['reviewer_name'])}, {format_datetime(inspection['master_reviewed_at'])}</p>")
    parts.append('<p>Клиент ____________________ / ____________________<br><br>Сотрудник ____________________ / ____________________</p>')
    parts.append('<p>Внутреннее документирование состояния автомобиля. Отметка сотрудника не заменяет подпись клиента.</p>')
    for number, photo in enumerate(inspection['photos'], 1):
        mark_number = next((i + 1 for i, mark in enumerate(inspection['marks']) if mark['id'] == photo['damage_mark_id']), None)
        parts.append(f"<h2 style='page-break-before:always'>Фотоприложение · {escape(snapshot['number'])} · Фото {number}</h2>"
            f"<p>{'Замечание № ' + str(mark_number) if mark_number else 'Общее фото осмотра'}<br>{escape(photo['caption'] or 'Без подписи')}</p>")
        try:
            image = load_photo(service.photo_path(order_id, photo['id']))
            key = f'inspection://photo/{photo["id"]}'
            resources[key] = image.scaled(1600, 2000, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            size = image.size().scaled(530, 650, Qt.AspectRatioMode.KeepAspectRatio)
            parts.append(f"<p><img src='{key}' width='{size.width()}' height='{size.height()}'></p>")
        except (ValueError, OSError) as exc:
            parts.append(f'<p>Фото недоступно: {escape(str(exc))}</p>')
    return ''.join(parts), resources


def add_image_resources(document, resources):
    for key, image in resources.items():
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(key), image)
