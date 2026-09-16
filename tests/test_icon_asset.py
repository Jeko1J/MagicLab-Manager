from pathlib import Path
import struct

import pytest
from PySide6.QtGui import QImage

from tools.build_icon import ICON_SIZES, build_icon

ROOT = Path(__file__).resolve().parents[1]


def test_ico_contains_decodable_sizes_and_preserves_source(tmp_path):
    source = ROOT / 'app' / 'resources' / 'images' / 'logo.png'
    before = source.read_bytes()
    output = tmp_path / 'magiclab.ico'
    build_icon(source, output)
    payload = output.read_bytes()
    stored = (ROOT / 'app' / 'resources' / 'icons' / 'magiclab.ico').read_bytes()
    assert struct.unpack_from('<HHH', payload) == (0, 1, len(ICON_SIZES))
    assert struct.unpack_from('<HHH', stored) == (0, 1, len(ICON_SIZES))
    for index, size in enumerate(ICON_SIZES):
        width, height, colors, reserved, planes, depth, length, offset = struct.unpack_from('<BBBBHHII', payload, 6 + 16 * index)
        assert (width or 256) == (height or 256) == size
        assert (colors, reserved, planes, depth) == (0, 0, 1, 32)
        frame = QImage.fromData(payload[offset:offset + length], 'PNG')
        assert not frame.isNull()
        assert frame.width() == frame.height() == size
        assert frame.pixelColor(0, 0).alpha() == 0
        assert any(frame.pixelColor(x, y).alpha() for y in range(size) for x in range(size))
        saved_entry = struct.unpack_from('<BBBBHHII', stored, 6 + 16 * index)
        assert saved_entry[:6] == (width, height, colors, reserved, planes, depth)
        saved_len, saved_offset = saved_entry[-2:]
        saved = QImage.fromData(stored[saved_offset:saved_offset + saved_len], 'PNG')
        assert not saved.isNull()
        assert saved.size() == frame.size()
        # QApplication меняет DPI в PNG, но не пиксели значка.
        fmt = QImage.Format.Format_RGBA8888
        assert bytes(frame.convertToFormat(fmt).constBits()) == bytes(saved.convertToFormat(fmt).constBits())
    assert source.read_bytes() == before


def test_missing_logo_cannot_replace_existing_icon(tmp_path):
    target = tmp_path / 'previous.ico'
    target.write_bytes(b'previous icon')
    with pytest.raises(ValueError, match='логотип'):
        build_icon(tmp_path / 'missing.png', target)
    assert target.read_bytes() == b'previous icon'
