"""Единая система координат схемы 800×440; в базе только доли от 0 до 1."""
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QPainter, QFont, QImage
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsSimpleTextItem
from PySide6.QtSvgWidgets import QGraphicsSvgItem

from app.config import RESOURCE_DIR
from app.inspection_catalog import BODY_ELEMENTS, DAMAGE_TYPES, SEVERITIES, SEVERITY_COLORS
from app.inspection_geometry import WIDTH, HEIGHT, element_at, project_marks


def build_scene(view, marks, parent=None):
    scene = QGraphicsScene(parent)
    scene.setSceneRect(-20, -20, WIDTH + 40, HEIGHT + 40)
    scene.setBackgroundBrush(QColor('#f3f4f5'))
    # Без ссылки сборщик мусора PySide удаляет SVG при открытии диалога.
    scene.schematic = QGraphicsSvgItem(str(RESOURCE_DIR / 'inspection' / f'{view.lower()}.svg'))
    scene.addItem(scene.schematic)
    markers = {}
    for number, mark in enumerate(project_marks(marks), 1):
        if mark['view'] != view:
            continue
        item = QGraphicsEllipseItem(-16, -16, 32, 32)
        item.setPos(mark['normalized_x'] * WIDTH, mark['normalized_y'] * HEIGHT)
        item.setBrush(QBrush(QColor(SEVERITY_COLORS[mark['severity']])))
        item.setPen(QPen(QColor('#ffffff'), 2))
        item.setZValue(2)
        item.setData(0, mark['id'])
        item.setToolTip(f"№ {number} · {BODY_ELEMENTS[mark['body_element']]}\n{DAMAGE_TYPES[mark['damage_type']]}\n"
                       f"{SEVERITIES[mark['severity']]} · ЛКП: {mark['paint_thickness_um'] if mark['paint_thickness_um'] is not None else '—'} мкм\n{mark['comment']}")
        label = QGraphicsSimpleTextItem(str(number), item)
        label.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        label.setBrush(QColor('white'))
        bounds = label.boundingRect()
        label.setPos(-bounds.width() / 2, -bounds.height() / 2)
        scene.addItem(item)
        markers[mark['id']] = item
    return scene, markers


class InspectionCanvas(QGraphicsView):
    point_clicked = Signal(float, float)
    marker_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editable = False
        self.markers = {}
        self._scene = None
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumSize(300, 210)
        self.setAccessibleName('Схема автомобиля. Выберите место дефекта или существующий маркер.')
        self.set_view('TOP', [])

    def set_view(self, view, marks):
        self.current_view = view
        old = self.scene()
        scene, self.markers = build_scene(view, marks, self)
        self._scene = scene
        self.setScene(scene)
        if old:
            old.deleteLater()
        self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.scene():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def highlight(self, mark_id):
        for identifier, item in self.markers.items():
            item.setPen(QPen(QColor('#152a3d' if identifier == mark_id else '#ffffff'), 4 if identifier == mark_id else 2))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            while item and item.data(0) is None:
                item = item.parentItem()
            if item:
                self.marker_clicked.emit(item.data(0))
                return
            point = self.mapToScene(event.position().toPoint())
            if self.editable and element_at(self.current_view, point.x() / WIDTH, point.y() / HEIGHT) is not None:
                self.point_clicked.emit(point.x() / WIDTH, point.y() / HEIGHT)
                return
        super().mousePressEvent(event)


def render_scheme(view, marks):
    scene, _ = build_scene(view, marks)
    image = QImage(840, 480, QImage.Format.Format_ARGB32)
    image.fill(QColor('#f3f4f5'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter, QRectF(0, 0, 840, 480), QRectF(-20, -20, 840, 480))
    painter.end()
    return image
