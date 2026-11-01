"""What the screen shows (panel.py): the tiles' layout and looks, pages, a touch shown at once, a tap, a light's
brightness by a long press, the screen going dark and waking, and only what changed drawn again, on a screen that
records what it's shown."""
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
    'sensor.motion': {'state': '2026-11-01T21:00:00+00:00',
                      'attributes': {'friendly_name': 'Last Motion', 'device_class': 'timestamp'}},
}
NOW = time.struct_time((2026, 11, 1, 21, 30, 0, 6, 305, 0))


class Backlight:
    def __init__(self):
        self.lit = True

    def on(self):
        self.lit = True

    def off(self):
        self.lit = False


class Screen:
    def __init__(self, size):
        self.size = size
        self.shown = []
        self.backlight = Backlight()

    def show(self, image, box=None):
        self.shown.append(box)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(size=(800, 480), entity_ids=('light.kitchen', 'light.porch', 'switch.fan', 'sensor.hall', 'light.gone')):
    screen = Screen(size)
    tapped, brightness = [], []
    clock = Clock()
    p = panel.Panel(screen, state=STATES.get, tapped=tapped.append,
                    brightness=lambda tile, percent: brightness.append((tile.entity_id, percent)),
                    now=lambda: NOW, clock=clock)
    p.set_tiles([panel.Tile(entity_id) for entity_id in entity_ids])
    p.clock_ = clock
    return screen, p, tapped, brightness


def middle(tile):
    return (tile.box[0] + tile.box[2]) // 2, (tile.box[1] + tile.box[3]) // 2


@pytest.mark.parametrize('count, size, expected', [
    (5, (776, 412), (3, 2)), (8, (776, 412), (3, 3)), (2, (776, 412), (2, 1)), (1, (776, 412), (1, 1)),
    (8, (456, 732), (2, 4)), (3, (456, 732), (1, 3))])
def test_the_grid_makes_the_tiles_as_large_as_they_can_be(count, size, expected):
    assert panel.grid(count, *size) == expected


@pytest.mark.parametrize('size', [(800, 480), (480, 800)])
@pytest.mark.parametrize('count', [1, 2, 5, 8])
def test_the_tiles_fill_the_screen_below_the_bar_without_overlapping(size, count):
    _, p, _, _ = make(size, ['sensor.s{}'.format(n) for n in range(count)])
    boxes = [tile.box for tile in p.tiles]
    for left, top, right, bottom in boxes:
        assert 0 <= left < right <= size[0] and panel.BAR_HEIGHT <= top < bottom <= size[1]
        assert bottom - top <= right - left  # never taller than wide
    for a in boxes:
        for b in boxes:
            assert a is b or a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


@pytest.mark.parametrize('entity_id, expected', [
    ('light.kitchen', ('Kitchen', 'On · 50%', True, True)),
    ('light.porch', ('Porch', 'Off', False, True)),
    ('sensor.hall', ('Hall', '19.5 °C', False, True)),
    ('binary_sensor.door', ('Door', 'On', True, True)),
    ('light.gone', ('Gone', 'Unavailable', False, False)),
    ('light.unknown', ('light.unknown', '—', False, False)),
    ('sensor.motion', ('Last Motion', '30 min ago', False, True)),
])
def test_how_each_kind_of_tile_looks(entity_id, expected):
    now = time.mktime(time.strptime('2026-11-01 21:30:00 UTC', '%Y-%m-%d %H:%M:%S %Z')) - time.timezone
    assert panel.Tile(entity_id).look(STATES.get(entity_id), now=now) == expected


@pytest.mark.parametrize('seconds, text', [(20, 'just now'), (125, '2 min ago'), (3 * 3600 + 5, '3 h ago'),
                                           (30 * 3600, 'yesterday'), (3 * 86400, '3 days ago')])
def test_a_time_is_shown_as_how_long_ago(seconds, text):
    assert panel.ago('2026-11-01T21:00:00+00:00', 1793566800 + seconds) == text


def test_a_name_of_its_own_replaces_home_assistants():
    assert panel.Tile('light.kitchen', 'Worktop').look(STATES['light.kitchen'])[0] == 'Worktop'


def test_a_long_name_wraps_onto_two_lines_and_shrinks_before_it_is_shortened():
    _, p, _, _ = make()
    font, lines = p.wrapped('Counter Top Left Under Cabinet', 160, 2, (30, 16))
    assert len(lines) == 2 and all(p.draw.textlength(line, font=font) <= 160 for line in lines)
    font, lines = p.wrapped('A name far too long to fit in two lines of a small tile at all', 120, 2, (30, 16))
    assert font.size == 16 and len(lines) == 2 and lines[1].endswith('…')
    _, lines = p.wrapped('SONOFF_SNZB_02LD_temperature', 120, 2, (24, 16))  # no spaces: split where it joins
    assert all(p.draw.textlength(line, font=p.font(16)) <= 120 for line in lines)


def test_a_word_shrinks_to_stay_whole_before_it_breaks_at_its_capitals():
    _, p, _, _ = make()
    font, lines = p.wrapped('CounterTopLeft', 200, 2, (30, 16))
    assert lines == ['CounterTopLeft'] and font.size < 30
    font, lines = p.wrapped('CounterTopLeftUnderTheCabinet', 140, 2, (30, 16))
    assert ''.join(lines) == 'CounterTopLeftUnderTheCabinet' and all(line[0].isupper() for line in lines)


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
        p.touched('up', 799, 479)
        p.touched('down', *middle(p.tiles[3]))  # a sensor
        p.touched('up', *middle(p.tiles[3]))
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

        left, top, right, bottom = p.slider_box()
        y = (top + bottom) // 2
        p.touched('down', left + (right - left) // 4, y)
        assert p.level == 25
        p.touched('move', right - 1, y)
        assert p.level == 100
        p.touched('up', right - 1, y)
        assert brightness == [('light.kitchen', 100)]

        p.touched('down', 5, p.height - 5)  # off the slider: closes it
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


def two_pages(size=(800, 480)):
    screen, p, tapped, brightness = make(size)
    p.set_pages([panel.Page('Kitchen', [panel.Tile('light.kitchen'), panel.Tile('switch.fan')]),
                  panel.Page('Hall', [panel.Tile('sensor.hall')])])
    p.show_all()
    return screen, p, tapped


def test_with_pages_the_bar_has_a_tab_for_each_and_a_tap_on_one_shows_it():
    async def test():
        _, p, _ = two_pages()
        assert len(p.tabs) == 2 and p.tiles[0].entity_id == 'light.kitchen'
        x = (p.tabs[1][0] + p.tabs[1][1]) // 2
        p.touched('down', x, 20)
        p.touched('up', x, 20)
        assert p.page == 1 and [t.entity_id for t in p.tiles] == ['sensor.hall']
    asyncio.run(test())


def test_a_swipe_changes_the_page_without_tapping_the_tile_it_began_on():
    async def test():
        _, p, tapped = two_pages()
        x, y = middle(p.tiles[1])
        p.touched('down', x, y)
        p.touched('move', x - 60, y)
        p.touched('up', x - 200, y + 10)
        assert p.page == 1 and tapped == []
        p.touched('down', 100, 300)
        p.touched('move', 400, 300)
        p.touched('up', 400, 300)
        assert p.page == 0
        p.touched('down', 400, 300)  # no page before the first
        p.touched('move', 700, 300)
        p.touched('up', 700, 300)
        assert p.page == 0
    asyncio.run(test())


def test_one_page_has_no_tabs_and_shows_the_date():
    _, p, _, _ = make()
    p.show_all()
    assert p.tabs == []


def test_the_screen_goes_dark_untouched_and_the_waking_touch_does_nothing_else():
    async def test():
        screen, p, tapped, _ = make()
        p.timeout = 60
        p.show_all()
        p.clock_.now += 59
        p.tick()
        assert screen.backlight.lit
        p.clock_.now += 2
        p.tick()
        assert not screen.backlight.lit and not p.awake

        x, y = middle(p.tiles[2])
        p.touched('down', x, y)
        assert screen.backlight.lit and p.awake
        p.touched('up', x, y)
        assert tapped == []  # only woke it
        p.touched('down', x, y)
        p.touched('up', x, y)
        assert tapped == [p.tiles[2]]
    asyncio.run(test())


def test_without_a_timeout_it_stays_lit():
    screen, p, _, _ = make()
    p.show_all()
    p.clock_.now += 10 ** 6
    p.tick()
    assert screen.backlight.lit


def test_without_tiles_the_screen_says_where_to_choose_them():
    screen, p, _, _ = make(entity_ids=())
    p.set_tiles([], hint='Choose tiles on http://panel.local')
    p.show_all()
    assert p.hint and screen.shown == [None]
