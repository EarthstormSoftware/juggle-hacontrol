"""What the screen shows (panel.py): the tiles' layout and looks, pages, a touch shown at once, a tap, what a long
press opens (a light's controls, a sensor's history: details.py), the screen going dark and waking, and only what
changed drawn again, on a screen that records what it's shown."""
import asyncio
import time

import pytest

import charts
import details
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
    'binary_sensor.hall_motion': {'state': 'off', 'attributes': {'friendly_name': 'Hall Motion',
                                                                 'device_class': 'motion'}},
    'light.strip': {'state': 'on', 'attributes': {
        'friendly_name': 'Strip', 'brightness': 255, 'supported_color_modes': ['color_temp', 'hs'],
        'color_mode': 'color_temp', 'color_temp_kelvin': 3000, 'min_color_temp_kelvin': 2000,
        'max_color_temp_kelvin': 6500, 'effect_list': ['Rainbow', 'Candle', 'Fireworks'], 'effect': 'Candle'}},
    'sensor.humidity': {'state': '55', 'attributes': {'friendly_name': 'Humidity', 'unit_of_measurement': '%',
                                                      'device_class': 'humidity'}},
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
                    adjust=lambda tile, data: brightness.append((tile.entity_id, data)),
                    now=lambda: NOW, clock=clock)
    p.set_tiles([panel.Tile(entity_id) for entity_id in entity_ids])
    p.clock_ = clock
    return screen, p, tapped, brightness


def middle(tile):
    return (tile.box[0] + tile.box[2]) // 2, (tile.box[1] + tile.box[3]) // 2


@pytest.mark.parametrize('size, expected', [((800, 480), (4, 3)), ((480, 800), (2, 5))])
def test_the_grid_has_cells_of_about_the_same_size_on_either_screen(size, expected):
    _, p, _, _ = make(size)
    assert p.grid == expected


def tiles(*sizes):
    return [panel.Tile('sensor.s{}'.format(n), size=size) for n, size in enumerate(sizes)]


@pytest.mark.parametrize('size', [(800, 480), (480, 800)])
@pytest.mark.parametrize('sizes', [['1x1'], ['1x1'] * 12, ['2x2', '1x2', '1x1', '4x1'], ['3x1', '2x1', '1x1', '1x1']])
def test_the_tiles_are_below_the_bar_without_overlapping(size, sizes):
    _, p, _, _ = make(size)
    p.set_tiles(tiles(*sizes))
    boxes = [tile.box for tile in p.tiles]
    for left, top, right, bottom in boxes:
        assert 0 <= left < right <= size[0] and panel.BAR_HEIGHT <= top < bottom <= size[1]
    for a in boxes:
        for b in boxes:
            assert a is b or a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_a_tile_takes_the_cells_its_size_says_and_a_small_one_fills_a_gap():
    _, p, _, _ = make()
    p.set_tiles(tiles('2x2', '3x1', '1x1', '1x2'))
    big, wide, small, tall = p.tiles
    one = p.tiles[2].box
    width, height = one[2] - one[0], one[3] - one[1]
    assert big.box[2] - big.box[0] == 2 * width + panel.GAP and big.box[3] - big.box[1] == 2 * height + panel.GAP
    assert wide.box[1] > big.box[3]  # no room for three across beside it: below
    assert small.box[0] == big.box[2] + panel.GAP and small.box[1] == big.box[1]  # beside it
    assert tall.box[3] - tall.box[1] == 2 * height + panel.GAP


def test_a_size_larger_than_the_grid_is_as_large_as_it_has():
    _, p, _, _ = make((480, 800))
    p.set_tiles(tiles('4x1'))
    assert p.tiles[0].span == (2, 1)


def test_tiles_that_dont_fit_are_left_off_and_the_bar_says_so():
    screen, p, _, _ = make()
    p.set_tiles(tiles('2x2', '2x2', '4x1', '2x2', '1x1'))
    assert len(p.tiles) == 3 and p.left_out == 2 and p.warning() == "2 tiles don't fit"
    p.show_all()
    p.set_status('Home Assistant: not connected')
    assert p.warning() == 'Home Assistant: not connected'


def test_an_auto_tile_is_one_cell_or_two_across_for_a_long_value():
    states = dict(STATES)
    states['sensor.words'] = {'state': 'Detected in the kitchen by the counter', 'attributes': {}}
    _, p, _, _ = make(entity_ids=('sensor.hall', 'sensor.words', 'switch.fan'))
    p.state = states.get
    p.set_tiles([panel.Tile('sensor.hall'), panel.Tile('sensor.words'), panel.Tile('switch.fan')])
    assert [tile.span for tile in p.tiles] == [(1, 1), (2, 1), (1, 1)]

    p.show_all()
    states['sensor.words'] = {'state': 'Clear', 'attributes': {}}
    p.changed(['sensor.words'])  # shorter now: the screen is laid out again
    assert p.tiles[1].span == (1, 1) and p.screen.shown[-1] is None


@pytest.mark.parametrize('text', ['19.5 °C', 'Detected in the kitchen by the counter top', 'On · 50%'])
@pytest.mark.parametrize('size', [(150, 60), (360, 60), (150, 200)])
def test_a_value_fits_in_its_room(text, size):
    _, p, _, _ = make()
    font, lines = p.fitted(text, size[0], size[1], panel.VALUE_SIZES, 3)
    assert all(p.draw.textlength(line, font=font) <= size[0] for line in lines)
    assert len(lines) * font.size + (len(lines) - 1) * panel.LINE_GAP <= size[1] or font.size == panel.VALUE_SIZES[1]
    assert font.size <= panel.VALUE_SIZES[0]


@pytest.mark.parametrize('entity_id, expected', [
    ('light.kitchen', ('Kitchen', 'On · 50%', True, True)),
    ('light.porch', ('Porch', 'Off', False, True)),
    ('sensor.hall', ('Hall', '19.5 °C', False, True)),
    ('binary_sensor.door', ('Door', 'On', True, True)),
    ('binary_sensor.hall_motion', ('Hall Motion', 'Clear', False, True)),
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


def hold(p, tile):
    """A long press on tile, and the finger lifting."""
    async def go():
        p.touched('down', *middle(tile))
        await asyncio.sleep(panel.LONG_PRESS + 0.1)
        p.touched('up', *middle(tile))
    return go()


def slider(p, what):
    return next(box for box, found in p.detail.sliders if found == what)


def button(p, what):
    return next(box for box, found in p.detail.buttons if found == what)


def tap(p, box):
    x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    p.touched('down', x, y)
    p.touched('up', x, y)


def test_holding_a_light_opens_its_controls_and_dragging_sets_its_brightness():
    async def test():
        screen, p, tapped, adjusted = make()
        p.show_all()
        await hold(p, p.tiles[0])  # the finger that held it: no tap, no change
        assert isinstance(p.detail, details.LightDetail) and p.detail.tile is p.tiles[0]
        assert tapped == [] and adjusted == []
        assert [what for _, what in p.detail.sliders] == ['brightness'] and p.detail.value('brightness') == 50

        left, top, right, bottom = slider(p, 'brightness')
        y = (top + bottom) // 2
        p.touched('down', left + (right - left) // 4, y)
        assert p.detail.value('brightness') == 25
        p.touched('move', right - 1, y)
        assert p.detail.value('brightness') == 100
        p.touched('up', right - 1, y)
        assert adjusted == [('light.kitchen', {'brightness_pct': 100})]
        p.touched('down', left - 5, y)  # to the very left: off
        p.touched('up', left - 5, y)
        assert adjusted[-1] == ('light.kitchen', {'brightness_pct': 0})

        tap(p, button(p, 'power'))
        assert tapped == [p.tiles[0]]
        p.touched('down', 5, p.height - 5)  # where there's nothing: closes it
        p.touched('up', 5, p.height - 5)
        assert p.detail is None and screen.shown[-1] is None
    asyncio.run(test())


def test_a_light_with_colours_and_effects_has_them_all():
    async def test():
        _, p, _, adjusted = make(entity_ids=('light.strip',))
        p.show_all()
        await hold(p, p.tiles[0])
        assert [what for _, what in p.detail.sliders] == ['brightness', 'warmth', 'colour']
        assert p.detail.value('warmth') == 3000 and p.detail.value('colour') is None  # showing a white

        left, top, right, bottom = slider(p, 'warmth')
        p.touched('down', right - 1, (top + bottom) // 2)
        p.touched('up', right - 1, (top + bottom) // 2)
        assert adjusted[-1] == ('light.strip', {'color_temp_kelvin': 6500})
        left, top, right, bottom = slider(p, 'colour')
        p.touched('down', (left + right) // 2, (top + bottom) // 2)
        p.touched('up', (left + right) // 2, (top + bottom) // 2)
        assert adjusted[-1] == ('light.strip', {'hs_color': [180, 100]})

        tap(p, button(p, ('effect', 'Fireworks')))
        assert adjusted[-1] == ('light.strip', {'effect': 'Fireworks'})
        tap(p, button(p, 'close'))
        assert p.detail is None
    asyncio.run(test())


def test_effects_that_dont_fit_are_shown_by_more():
    async def test():
        states = dict(STATES)
        many = ['Effect number {}'.format(n) for n in range(60)]
        states['light.strip'] = dict(STATES['light.strip'], attributes=dict(STATES['light.strip']['attributes'],
                                                                             effect_list=many))
        _, p, _, _ = make(entity_ids=('light.strip',))
        p.state = states.get
        p.show_all()
        await hold(p, p.tiles[0])
        shown = [what[1] for _, what in p.detail.buttons if isinstance(what, tuple)]
        assert 0 < len(shown) < 60 and shown == many[:len(shown)]
        for _, (left, top, right, bottom) in [(0, box) for box, _ in p.detail.buttons]:
            assert bottom <= p.height and right <= p.width
        tap(p, button(p, 'more'))
        assert [what[1] for _, what in p.detail.buttons if isinstance(what, tuple)][0] == many[len(shown)]
    asyncio.run(test())


def test_a_light_that_only_switches_isnt_held_nor_one_whose_finger_moved():
    async def test():
        _, p, tapped, _ = make()
        p.touched('down', *middle(p.tiles[1]))  # on and off only
        await asyncio.sleep(panel.LONG_PRESS + 0.1)
        assert p.detail is None
        p.touched('up', *middle(p.tiles[1]))
        assert tapped == [p.tiles[1]]

        p.touched('down', *middle(p.tiles[0]))
        p.touched('move', *middle(p.tiles[2]))
        await asyncio.sleep(panel.LONG_PRESS + 0.1)
        assert p.detail is None
    asyncio.run(test())


HOUR = 3600
WALL = 1793566800.0


def with_history(entity_ids=('sensor.hall', 'binary_sensor.hall_motion'), points=None):
    asked = []

    async def history(entity_id, hours):
        asked.append((entity_id, hours))
        return points or [(WALL - 30 * HOUR, '18'), (WALL - 3 * HOUR, '19.5'), (WALL - HOUR, 'unavailable'),
                          (WALL - HOUR / 2, '20')]
    screen, p, tapped, adjusted = make(entity_ids=entity_ids)
    p.history = history
    p.wall = lambda: WALL
    return screen, p, asked


def test_holding_a_sensor_opens_its_history_over_the_tiles_hours_and_a_tap_chooses_others():
    async def test():
        screen, p, asked = with_history()
        p.tiles[0].hours = 6
        p.show_all()
        await hold(p, p.tiles[0])
        assert isinstance(p.detail, details.HistoryDetail) and p.detail.hours == 6
        await asyncio.sleep(0.01)
        assert asked == [('sensor.hall', 6)] and p.histories['sensor.hall', 6].points
        assert screen.shown[-1] == p.detail.area()  # drawn again with it

        tap(p, button(p, ('hours', 168)))
        await asyncio.sleep(0.01)
        assert p.detail.hours == 168 and asked[-1] == ('sensor.hall', 168)
        tap(p, button(p, ('hours', 6)))
        assert asked[-1] == ('sensor.hall', 168)  # still fresh: not asked again

        tap(p, button(p, 'close'))
        await hold(p, p.tiles[1])  # a binary sensor's: a timeline
        await asyncio.sleep(0.01)
        assert p.detail.tile.entity_id == 'binary_sensor.hall_motion'
    asyncio.run(test())


def test_without_a_history_a_sensor_isnt_held():
    async def test():
        _, p, _, _ = make()
        p.touched('down', *middle(p.tiles[3]))
        await asyncio.sleep(panel.LONG_PRESS + 0.1)
        assert p.detail is None
    asyncio.run(test())


def test_a_graph_tile_asks_for_its_history_and_adds_what_changes():
    async def test():
        states = dict(STATES)
        screen, p, asked = with_history(entity_ids=('sensor.hall',))
        p.state = states.get
        p.set_tiles([panel.Tile('sensor.hall', show='graph', hours=6)])
        p.show_all()
        await asyncio.sleep(0.01)
        assert asked == [('sensor.hall', 6)] and screen.shown[-1] == p.tiles[0].box
        found = p.histories['sensor.hall', 6]
        assert found.points[0] == (WALL - 30 * HOUR, '18')

        p.wall = lambda: WALL + 4 * HOUR
        states['sensor.hall'] = dict(STATES['sensor.hall'], state='21')
        p.changed(['sensor.hall'])
        assert found.points[-1] == (WALL + 4 * HOUR, '21')
        assert found.points[0] == (WALL - 3 * HOUR, '19.5')  # the state the six hours began with
        assert len(asked) == 1
    asyncio.run(test())


def test_a_sensor_shows_a_gauge_or_graph_only_when_its_a_number():
    tile = panel.Tile('sensor.hall', show='gauge')
    assert tile.showing(STATES['sensor.hall']) == 'gauge'
    assert tile.showing({'state': 'unavailable', 'attributes': {}}) == 'value'
    assert tile.showing({'state': 'Clear', 'attributes': {}}) == 'value'
    assert panel.Tile('binary_sensor.door', show='gauge').showing(STATES['binary_sensor.door']) == 'value'
    assert panel.Tile('binary_sensor.door', show='graph').showing(STATES['binary_sensor.door']) == 'graph'
    assert panel.Tile('sensor.humidity', show='gauge').gauge_range(STATES['sensor.humidity']) == (0, 100)
    assert panel.Tile('sensor.hall', gauge=(10, 25)).gauge_range(STATES['sensor.hall']) == (10, 25)


def test_an_icon_is_the_one_its_kind_suits_or_the_one_chosen():
    assert panel.Tile('binary_sensor.hall_motion', icon='auto').icon_name(STATES['binary_sensor.hall_motion']) \
        == 'motion'
    assert panel.Tile('sensor.humidity', icon='auto').icon_name(STATES['sensor.humidity']) == 'drop'
    assert panel.Tile('light.kitchen', icon='auto').icon_name(STATES['light.kitchen']) == 'bulb'
    assert panel.Tile('sensor.hall', icon='sun').icon_name(STATES['sensor.hall']) == 'sun'
    assert panel.Tile('sensor.hall').icon_name(STATES['sensor.hall']) is None


@pytest.mark.parametrize('size', [(800, 480), (480, 800)])
@pytest.mark.parametrize('names, values', [('fit', 'fit'), ('small', 'xlarge'), ('large', 'small'),
                                           ('medium', 'large'), ('fit', 'medium')])
def test_every_kind_of_tile_draws_in_every_text_size(size, names, values):
    states = dict(STATES)
    _, p, _ = with_history()[:3]
    p.state = states.get
    p.set_pages([panel.Page('', [
        panel.Tile('sensor.hall', icon='auto', show='graph'), panel.Tile('sensor.humidity', show='gauge'),
        panel.Tile('binary_sensor.hall_motion', icon='auto', show='graph'),
        panel.Tile('light.strip', icon='auto', size='2x1'), panel.Tile('sensor.motion', icon='clock')], names, values)])
    p.histories['sensor.hall', 24] = history = panel.History()
    history.points = [(WALL - 30 * HOUR, '18'), (WALL - HOUR, '20')]
    p.histories['binary_sensor.hall_motion', 24] = motion = panel.History()
    motion.points = [(WALL - 30 * HOUR, 'off'), (WALL - HOUR, 'on'), (WALL - HOUR / 2, 'off')]
    p.show_all()


def test_with_one_text_size_every_tiles_value_is_that_size_and_each_page_has_its_own():
    _, p, _, _ = make()
    p.set_pages([panel.Page('Small', [panel.Tile(entity_id) for entity_id in STATES], 'large', 'small'),
                 panel.Page('Fitted', [])])
    names, values = set(), set()
    real = p.draw.text

    def text(xy, line, font=None, **kwargs):
        (values if kwargs.get('anchor') == 'ls' else names).add(font.size)
        return real(xy, line, font=font, **kwargs)
    p.draw.text = text
    p.show_all()
    assert values == {panel.VALUE_TEXT['small']}
    assert panel.NAME_TEXT['large'] in names and max(names - {26}) == panel.NAME_TEXT['large']  # 26: the clock's
    p.go_to(1)
    assert (p.name_text, p.value_text) == ('fit', 'fit')


def test_content_too_long_for_its_tile_at_its_size_shrinks_rather_than_being_cut_short():
    _, p, _, _ = make()
    p.set_pages([panel.Page('', [panel.Tile('light.kitchen', size='1x1')], value_size='xlarge')])
    tile = p.tiles[0]
    width = tile.box[2] - tile.box[0] - 2 * panel.PADDING
    font, lines = p.fitted('On · 50%', width, 60, p.value_sizes(tile), 1)
    assert font.size < panel.VALUE_TEXT['xlarge'] and not lines[0].endswith('…')


def test_a_history_as_spans_and_a_line():
    points = [(100, 'off'), (150, 'on'), (180, 'off')]
    assert charts.spans(points, 120, 200) == [(120, 150, 'off'), (150, 180, 'on'), (180, 200, 'off')]
    _, p, _, _ = make()
    assert charts.line(p.draw, (0, 0, 100, 50), [(0, '1'), (50, 'x'), (60, '3')], 0, 100, (255, 255, 255)) \
        == charts.value_range([1, 3])
    assert charts.line(p.draw, (0, 0, 100, 50), [(0, 'unknown')], 0, 100, (255, 255, 255)) is None


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
