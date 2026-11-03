"""The tiles' icons (kinds.ICONS), drawn with Pillow's lines and shapes so no icon font is needed.

Each is drawn on a grid of 24 x 24 units, four times larger than it's shown and then shrunk, which smooths its edges
(Pillow's shapes aren't anti-aliased). What's drawn is a mask, kept for each name and size, that the panel fills with
the tile's colour.
"""
import math

from PIL import Image, ImageDraw

LARGER = 4
STROKE = 2  # units


def _circle(d, s, x, y, r, fill=False):
    box = (s(x - r), s(y - r), s(x + r), s(y + r))
    if fill:
        d.ellipse(box, fill=255)
    else:
        d.ellipse(box, outline=255, width=s(STROKE))


def _lines(d, s, *points, closed=False):
    points = [(s(x), s(y)) for x, y in points] + ([(s(points[0][0]), s(points[0][1]))] if closed else [])
    d.line(points, fill=255, width=s(STROKE), joint='curve')
    for x, y in (points[0], points[-1]):  # round ends
        r = s(STROKE) / 2
        d.ellipse((x - r, y - r, x + r, y + r), fill=255)


def _box(d, s, left, top, right, bottom, radius=2, fill=False):
    box = (s(left), s(top), s(right), s(bottom))
    if fill:
        d.rounded_rectangle(box, radius=s(radius), fill=255)
    else:
        d.rounded_rectangle(box, radius=s(radius), outline=255, width=s(STROKE))


def _bulb(d, s):
    _circle(d, s, 12, 9.5, 6.5)
    _lines(d, s, (9.5, 15), (9.5, 18), (14.5, 18), (14.5, 15))
    _lines(d, s, (10, 21), (14, 21))


def _plug(d, s):
    _lines(d, s, (9, 3), (9, 8))
    _lines(d, s, (15, 3), (15, 8))
    _box(d, s, 5.5, 8, 18.5, 15, 3)
    _lines(d, s, (12, 15), (12, 21))


def _thermometer(d, s):
    _box(d, s, 9.5, 2, 14.5, 15, 2.5)
    _circle(d, s, 12, 18, 4, fill=True)
    _lines(d, s, (12, 8), (12, 16))


def _drop(d, s):
    points = [(12, 2)]
    for step in range(0, 241, 15):  # around the bottom, from the right side to the left
        angle = math.radians(-30 + step)
        points.append((12 + 6.5 * math.cos(angle), 15 + 6.5 * math.sin(angle)))
    _lines(d, s, *points, closed=True)


def _motion(d, s):
    _circle(d, s, 14, 4, 2.2, fill=True)
    _lines(d, s, (13.5, 8), (11, 14))
    _lines(d, s, (8, 10), (13.5, 8), (17, 11.5))
    _lines(d, s, (11, 14), (15, 17.5), (14, 22))
    _lines(d, s, (11, 14), (8.5, 18.5), (4.5, 19.5))


def _door(d, s):
    _lines(d, s, (6, 22), (6, 2), (18, 2), (18, 22))
    _lines(d, s, (3, 22), (21, 22))
    _circle(d, s, 15, 12.5, 1.3, fill=True)


def _window(d, s):
    _box(d, s, 4, 3, 20, 21, 1.5)
    _lines(d, s, (12, 3), (12, 21))
    _lines(d, s, (4, 12), (20, 12))


def _battery(d, s):
    _box(d, s, 2.5, 7, 19, 17, 2)
    _box(d, s, 19, 10, 22, 14, 1, fill=True)
    _box(d, s, 5, 9.5, 13, 14.5, 1, fill=True)


def _sun(d, s):
    _circle(d, s, 12, 12, 4.5)
    for n in range(8):
        angle = math.radians(n * 45)
        _lines(d, s, (12 + 7.5 * math.cos(angle), 12 + 7.5 * math.sin(angle)),
               (12 + 10 * math.cos(angle), 12 + 10 * math.sin(angle)))


def _bolt(d, s):
    d.polygon([(s(x), s(y)) for x, y in ((14, 1.5), (4.5, 13.5), (11, 13.5), (9.5, 22.5), (19.5, 9.5),
                                         (13, 9.5))], fill=255)


def _alert(d, s):
    _lines(d, s, (12, 3), (22, 20.5), (2, 20.5), closed=True)
    _lines(d, s, (12, 9), (12, 14))
    _circle(d, s, 12, 17.3, 1.3, fill=True)


def _clock(d, s):
    _circle(d, s, 12, 12, 9.5)
    _lines(d, s, (12, 6.5), (12, 12), (16, 14))


def _gauge(d, s):
    box = (s(2.5), s(4), s(21.5), s(23))
    d.arc(box, 150, 390, fill=255, width=s(STROKE))
    _lines(d, s, (12, 13.5), (16.5, 8))
    _circle(d, s, 12, 13.5, 2, fill=True)


def _signal(d, s):
    for n, top in enumerate((17, 13, 9, 4)):
        _box(d, s, 3 + 5 * n, top, 6 + 5 * n, 21, 0.8, fill=True)


def _lock(d, s):
    _box(d, s, 4.5, 11, 19.5, 21.5, 2)
    d.arc((s(7.5), s(3), s(16.5), s(13)), 180, 360, fill=255, width=s(STROKE))
    _lines(d, s, (7.5, 8), (7.5, 11))
    _lines(d, s, (16.5, 8), (16.5, 11))


def _air(d, s):
    for y, end in ((7, 15), (12, 19), (17, 12)):
        _lines(d, s, (3, y), (end, y))
    d.arc((s(13), s(3), s(19), s(9)), 180, 450, fill=255, width=s(STROKE))
    d.arc((s(17), s(8), s(23), s(14)), 180, 450, fill=255, width=s(STROKE))
    d.arc((s(10), s(15), s(16), s(21)), 270, 540, fill=255, width=s(STROKE))


DRAWN = {'bulb': _bulb, 'plug': _plug, 'thermometer': _thermometer, 'drop': _drop, 'motion': _motion, 'door': _door,
         'window': _window, 'battery': _battery, 'sun': _sun, 'bolt': _bolt, 'alert': _alert, 'clock': _clock,
         'gauge': _gauge, 'signal': _signal, 'lock': _lock, 'air': _air}
_masks = {}


def mask(name, size):
    """The icon as a mask (an 'L' image, size x size), or None for a name it doesn't know."""
    if name not in DRAWN or size < 4:
        return None
    if (name, size) not in _masks:
        larger = size * LARGER
        image = Image.new('L', (larger, larger), 0)
        DRAWN[name](ImageDraw.Draw(image), lambda units: round(units * larger / 24))
        _masks[name, size] = image.resize((size, size), Image.Resampling.LANCZOS)
    return _masks[name, size]


def draw(image, name, left, top, size, colour):
    """The icon on image at (left, top), size across, in colour."""
    found = mask(name, size)
    if found:
        image.paste(colour, (round(left), round(top), round(left) + size, round(top) + size), found)
