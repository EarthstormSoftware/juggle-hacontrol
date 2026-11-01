"""What the screen shows (panel.py): the tiles' layout and looks, a touch shown at once, a tap, a light's brightness
by a long press, and only what changed drawn again, on a screen that records what it's shown."""
import asyncio
import time

import pytest

import panel

STATES = {
    'light.kitchen': {'state': 'on', 'attributes': {'friendly_name': 'Kitchen', 'brightness': 128,
                                                    'supported_color_modes': ['brightness']}},
    'light.porch': {'state': 'off', 'attributes': {'friendly_name': 'Porch', 'supported_color_modes': ['onoff']}},
    'switch.fan': {'state': 'off', 'attributes': {'friendly_name': 'Fan'}},
    'sensor.hall': {'state': '19.5', 'attributes': {'friendly_name': 'Hall', 'unit_of_measurement': '°C'}},
    'binary_sensor.door': {'state': 'on', 'attributes': {'friendly_name': 'Door'}},
    'light.gone': {'state': 'unavailable', 'attributes': {'friendly_name': 'Gone'}},
}


class Screen:
    def __init__(self, size):
        self.size = size
        self.shown = []

    def show(self, image, box=None):
        self.shown.append(box)


def make(size=(800, 480), entity_ids=('light.kitchen', 'light.porch', 'switch.fan', 'sensor.hall', 'light.gone')):
    screen = Screen(size)
    tapped, brightness = [], []
    p = panel.Panel(screen, state=STATES.get, tapped=tapped.append,
                    brightness=lambda tile, percent: brightness.append((tile.entity_id, percent)),
                    now=lambda: time.struct_time((2026, 11, 1, 21, 30, 0, 6, 305, 0)))
    p.set_tiles([panel.Tile(entity_id) for entity_id in entity_ids])
    return screen, p, tapped, brightness


def middle(tile):
    return (tile.box[0] + tile.box[2]) // 2, (tile.box[1] + tile.box[3]) // 2


@pytest.mark.parametrize('size, across', [((800, 480), 4), ((480, 800), 2)])
def test_as_many_tiles_across_as_fit_inside_the_screen(size, across):
    _, p, _, _ = make(size)
    tops = sorted({tile.box[1] for tile in p.tiles})
    assert sum(1 for tile in p.tiles if tile.box[1] == tops[0]) == across
    for tile in p.tiles:
        left, top, right, bottom = tile.box
        assert 0 <= left < right <= size[0] and panel.CLOCK_HEIGHT <= top < bottom <= size[1] - panel.STATUS_HEIGHT


@pytest.mark.parametrize('size', [(800, 480), (480, 800)])
def test_the_most_tiles_fit_on_the_screen(size):
    _, p, _, _ = make(size, ['sensor.s{}'.format(n) for n in range(panel.MOST_TILES + 3)])
    assert len(p.tiles) == panel.MOST_TILES
    assert max(tile.box[3] for tile in p.tiles) <= size[1] - panel.STATUS_HEIGHT


@pytest.mark.parametrize('entity_id, expected', [
    ('light.kitchen', ('Kitchen', 'On · 50%', True, True)),
    ('light.porch', ('Porch', 'Off', False, True)),
    ('sensor.hall', ('Hall', '19.5 °C', False, True)),
    ('binary_sensor.door', ('Door', 'On', True, True)),
    ('light.gone', ('Gone', 'Unavailable', False, False)),
    ('light.unknown', ('light.unknown', '—', False, False)),
])
def test_how_each_kind_of_tile_looks(entity_id, expected):
    assert panel.Tile(entity_id).look(STATES.get(entity_id)) == expected


def test_a_name_of_its_own_replaces_home_assistants():
    assert panel.Tile('light.kitchen', 'Worktop').look(STATES['light.kitchen'])[0] == 'Worktop'


def test_the_whole_screen_is_shown_first_then_only_what_changes():
    screen, p, _, _ = make()
    p.show_all()
    assert screen.shown == [None]
    p.changed(['sensor.hall'])
    assert screen.shown == [None, p.tiles[3].box]
    p.changed(None)
    assert screen.shown[2:] == [tile.box for tile in p.tiles]


def test_a_tap_shows_at_once_and_asks_home_assistant_drawing_only_the_tile():
    async def test():
        screen, p, tapped, _ = make()
        x, y = middle(p.tiles[2])
        p.touched('down', x, y)
        assert screen.shown == [p.tiles[2].box] and p.pressed is p.tiles[2]
        p.touched('up', x + 3, y + 3)
        assert screen.shown == [p.tiles[2].box] * 2 and tapped == [p.tiles[2]] and p.pressed is None
    asyncio.run(test())


def test_lifting_off_the_tile_or_touching_a_sensor_does_nothing():
    async def test():
        screen, p, tapped, _ = make()
        p.touched('down', *middle(p.tiles[1]))
        p.touched('up', 799, 0)
        p.touched('down', *middle(p.tiles[3]))  # a sensor
        p.touched('up', *middle(p.tiles[3]))
        p.touched('down', 2, 2)  # between tiles
        p.touched('up', 2, 2)
        assert tapped == [] and screen.shown == [p.tiles[1].box] * 2
    asyncio.run(test())


def test_holding_a_light_opens_its_brightness_and_dragging_sets_it():
    async def test():
        screen, p, tapped, brightness = make()
        p.show_all()
        p.touched('down', *middle(p.tiles[0]))
        await asyncio.sleep(panel.LONG_PRESS + 0.1)
        assert p.adjusting is p.tiles[0] and p.level == 50
        p.touched('up', *middle(p.tiles[0]))  # the finger that held it: no tap, no change
        assert tapped == [] and brightness == [] and p.adjusting is p.tiles[0]

        left, top, right, bottom = p.bar_box()
        y = (top + bottom) // 2
        p.touched('down', left + (right - left) // 4, y)
        assert p.level == 25
        p.touched('move', right - 1, y)
        assert p.level == 100
        p.touched('up', right - 1, y)
        assert brightness == [('light.kitchen', 100)]

        p.touched('down', 5, p.height - 5)  # off the bar: closes it
        p.touched('up', 5, p.height - 5)
        assert p.adjusting is None and screen.shown[-1] is None
    asyncio.run(test())


def test_a_light_without_brightness_or_a_moved_finger_isnt_held():
    async def test():
        _, p, tapped, _ = make()
        p.touched('down', *middle(p.tiles[1]))  # on and off only
        await asyncio.sleep(panel.LONG_PRESS + 0.1)
        assert p.adjusting is None
        p.touched('up', *middle(p.tiles[1]))
        assert tapped == [p.tiles[1]]

        p.touched('down', *middle(p.tiles[0]))
        p.touched('move', *middle(p.tiles[2]))
        await asyncio.sleep(panel.LONG_PRESS + 0.1)
        assert p.adjusting is None
    asyncio.run(test())


def test_without_tiles_the_screen_says_where_to_choose_them():
    screen, p, _, _ = make(entity_ids=())
    p.set_tiles([], hint='Choose tiles on http://panel.local')
    p.show_all()
    assert p.hint and screen.shown == [None]


def test_long_text_is_shortened_to_fit():
    _, p, _, _ = make()
    text = panel.fitted(p.draw, 'A very long name for a light in the house', p.fonts[24], 140)
    assert text.endswith('…') and p.draw.textlength(text, font=p.fonts[24]) <= 140
