"""Геометрия схемы 800×440: точка вне детали переносится в её опорную точку.
При показе старых записей координаты в БД не меняются.
"""
from dataclasses import dataclass

WIDTH, HEIGHT = 800, 440


@dataclass(frozen=True)
class BodyRegion:
    element: str
    polygon: tuple[tuple[float, float], ...]
    anchor: tuple[float, float]

    def contains(self, x, y):
        inside = False
        for (ax, ay), (bx, by) in zip(self.polygon, self.polygon[1:] + self.polygon[:1]):
            # Граница тоже принадлежит детали.
            if abs((x-ax)*(by-ay)-(y-ay)*(bx-ax)) < 1e-7 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
                return True
            if (ay > y) != (by > y) and x < (bx-ax)*(y-ay)/(by-ay)+ax:
                inside = not inside
        return inside


def rect(element, left, top, right, bottom):
    return BodyRegion(element, ((left, top), (right, top), (right, bottom), (left, bottom)),
                      ((left+right)/2, (top+bottom)/2))


LEFT_REGIONS = (
    BodyRegion('LEFT_MIRROR', ((518,192),(542,181),(556,191),(547,208),(525,206)), (537,196)),
    rect('LEFT_FRONT_DOOR', 385, 207, 531, 281),
    BodyRegion('LEFT_REAR_DOOR', ((215,212),(273,205),(367,205),(367,282),(260,282)), (310,245)),
    rect('LEFT_SILL', 271, 284, 541, 299),
    BodyRegion('LEFT_FRONT_FENDER', ((555,211),(645,220),(652,255),(560,254)), (601,237)),
    BodyRegion('LEFT_REAR_FENDER', ((132,223),(190,202),(220,205),(233,245),(157,253)), (180,230)),
    BodyRegion('FRONT_BUMPER', ((659,249),(705,249),(705,285),(659,295)), (683,271)),
    rect('REAR_BUMPER', 94, 263, 153, 290),
    BodyRegion('HOOD', ((573,196),(686,216),(687,222),(573,208)), (622,211)),
    BodyRegion('TRUNK', ((96,217),(190,195),(197,202),(96,225)), (153,211)),
    rect('ROOF', 309, 110, 456, 126),
)

# На правой схеме автомобиль зеркально развёрнут: перед находится слева.
RIGHT_REGIONS = tuple(BodyRegion(region.element.replace('LEFT_', 'RIGHT_'),
    tuple((WIDTH-x, y) for x, y in region.polygon), (WIDTH-region.anchor[0], region.anchor[1]))
    for region in LEFT_REGIONS)

REGIONS = {
    'LEFT': LEFT_REGIONS,
    'RIGHT': RIGHT_REGIONS,
    'TOP': (
        rect('ROOF', 305, 143, 447, 297),
        rect('HOOD', 490, 157, 643, 283),
        rect('TRUNK', 181, 140, 252, 300),
        BodyRegion('LEFT_MIRROR', ((466,103),(476,79),(499,81),(495,107)), (484,95)),
        BodyRegion('RIGHT_MIRROR', ((466,337),(476,361),(499,359),(495,333)), (484,345)),
        rect('LEFT_FRONT_DOOR', 369, 107, 463, 126),
        rect('LEFT_REAR_DOOR', 258, 107, 365, 126),
        rect('RIGHT_FRONT_DOOR', 369, 314, 463, 333),
        rect('RIGHT_REAR_DOOR', 258, 314, 365, 333),
        rect('LEFT_FRONT_FENDER', 500, 112, 641, 153),
        rect('RIGHT_FRONT_FENDER', 500, 287, 641, 328),
        rect('LEFT_REAR_FENDER', 181, 113, 253, 137),
        rect('RIGHT_REAR_FENDER', 181, 303, 253, 328),
        rect('FRONT_BUMPER', 649, 152, 677, 288),
        rect('REAR_BUMPER', 138, 153, 175, 287),
    ),
    'FRONT': (
        rect('FRONT_BUMPER', 211, 267, 589, 321),
        BodyRegion('HOOD', ((267,198),(533,198),(518,237),(282,237)), (400,218)),
        BodyRegion('RIGHT_MIRROR', ((217,190),(187,183),(177,195),(181,210),(211,214)), (197,200)),
        BodyRegion('LEFT_MIRROR', ((583,190),(613,183),(623,195),(619,210),(589,214)), (603,200)),
        rect('RIGHT_FRONT_FENDER', 198, 216, 222, 261),
        rect('LEFT_FRONT_FENDER', 578, 216, 602, 261),
        rect('ROOF', 285, 96, 515, 112),
    ),
    'REAR': (
        rect('REAR_BUMPER', 211, 287, 589, 321),
        rect('TRUNK', 299, 208, 501, 280),
        BodyRegion('LEFT_MIRROR', ((217,190),(187,183),(177,195),(181,210),(211,214)), (197,200)),
        BodyRegion('RIGHT_MIRROR', ((583,190),(613,183),(623,195),(619,210),(589,214)), (603,200)),
        rect('LEFT_REAR_FENDER', 198, 216, 220, 281),
        rect('RIGHT_REAR_FENDER', 580, 216, 602, 281),
        rect('ROOF', 285, 96, 515, 112),
    ),
}

# Контур кузова для «Другого» (стёкла, оптика и невыделенные детали).
OUTLINES = {
    'TOP': ((185,105),(622,105),(680,156),(680,284),(622,335),(185,335),(135,280),(135,160)),
    'LEFT': ((92,282),(94,223),(191,198),(272,122),(310,109),(461,109),(502,128),(570,196),(687,216),(707,247),(707,286),(656,299),(557,299),(256,299),(157,299),(105,296)),
    'FRONT': ((191,239),(211,202),(251,114),(281,94),(519,94),(549,114),(589,202),(609,239),(609,305),(580,325),(220,325),(191,305)),
}
OUTLINES['RIGHT'] = tuple((WIDTH-x, y) for x, y in OUTLINES['LEFT'])
OUTLINES['REAR'] = OUTLINES['FRONT']

PREFERRED_VIEW = {'ROOF': 'TOP', 'HOOD': 'TOP', 'TRUNK': 'REAR',
                  'FRONT_BUMPER': 'FRONT', 'REAR_BUMPER': 'REAR'}


def region_for(view, element):
    return next((region for region in REGIONS.get(view, ()) if region.element == element), None)


def element_at(view, nx, ny):
    x, y = nx*WIDTH, ny*HEIGHT
    for region in REGIONS.get(view, ()):
        if region.contains(x, y):
            return region.element
    outline = OUTLINES.get(view)
    if outline and BodyRegion('OTHER', outline, (400, 220)).contains(x, y):
        # Колёса не относятся к ЛКП кузова.
        if view in ('LEFT', 'RIGHT'):
            wheel_x = (207, 606) if view == 'LEFT' else (593, 194)
            if any((x-cx)**2+(y-299)**2 < 49**2 for cx in wheel_x):
                return None
        return 'OTHER'
    return None


def position_matches(view, element, nx, ny):
    if element == 'OTHER':
        return element_at(view, nx, ny) is not None
    region = region_for(view, element)
    return bool(region and region.contains(nx*WIDTH, ny*HEIGHT))


def place_mark(values):
    """Сохраняет точную корректную точку; иначе предлагает центр нужной детали."""
    result = dict(values)
    view, element = values['view'], values['body_element']
    if position_matches(view, element, values['normalized_x'], values['normalized_y']):
        return result
    if element == 'OTHER':
        x, y = 400, 220
    else:
        view = PREFERRED_VIEW.get(element, 'LEFT' if element.startswith('LEFT_') else 'RIGHT')
        region = region_for(view, element)
        if region is None:
            raise ValueError('Для элемента кузова не задана область схемы')
        x, y = region.anchor
    result.update(view=view, normalized_x=x/WIDTH, normalized_y=y/HEIGHT)
    return result


def project_marks(marks):
    """Только представление. Уточнение старых координат требует сохранения пользователем."""
    projected = []
    for mark in marks:
        value = place_mark(mark)
        changed = any(value[key] != mark[key] for key in ('view', 'normalized_x', 'normalized_y'))
        value['position_adjusted'] = changed or mark.get('position_adjusted', False)
        projected.append(value)
    return projected
