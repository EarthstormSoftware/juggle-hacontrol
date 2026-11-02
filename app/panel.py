"""What the screen shows: a bar along the top (the date and time, and what's wrong when something is), and the
tiles in a grid of cells below it (4 across and 3 down in landscape). Each tile has a size in cells (2x1: two across,
one down), or 'auto': one cell, or two across when its value wouldn't fit in one. The tiles go across then down, each
in the first place it fits (so a small tile can fill a gap a larger one left); one that fits nowhere is left off, and
the bar says so.

The tiles are in pages, each with a name: with more than one, the bar has a tab for each in place of the date, and
a page is chosen by tapping its tab or by swiping across the screen.

Each tile is a Home Assistant entity, chosen on the page: a light or switch (a tap toggles it; a light's long press
opens its brightness), or a sensor (its state and unit; a time as how long ago). A tile's name is in a band across
its top, wrapping onto a second line and shrinking to fit; its value is sized to the tile, a sensor's onto more
lines when it's long. A touch shows at once on the tile it's on, and a tap (lifted on the same tile)
acts. Only what changed is drawn again: a tile, or the bar when the minute changes. Home Assistant answers a tap with
the entity's new state, which redraws the tile.

The brightness is a slider across the screen, over the tiles: dragging along it sets the brightness (sent when the
finger lifts), and a tap off it closes it.

The screen goes dark after the time set without a touch (the backlight off), and the next touch only wakes it.
"""
import asyncio
import math
import time
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (18, 20, 26)
BAR = (28, 31, 40)
TEXT = (235, 235, 240)
MUTED = (150, 155, 170)
FAINT = (90, 95, 110)
TILE = (44, 48, 60)
TILE_ON = (250, 190, 70)
# The band with the tile's name
BAND = (64, 70, 88)
BAND_ON = (214, 156, 44)
TEXT_ON = (24, 22, 18)
WARNING = (240, 150, 90)
# How much lighter a tile is while it's touched
PRESSED = 40
MARGIN = 12
GAP = 12
BAR_HEIGHT = 48
TAB_PADDING = 14
# How far a finger moves across to change the page, and how far before it's a swipe rather than a press
SWIPE = 100
SWIPE_START = 30
PADDING = 12
BAND_PADDING = 7
RADIUS = 16
# About how large a cell is: the grid has as many as come closest to it
CELL = (190, 136)
# A tile's size in cells, across x down
SIZES = ('auto', '1x1', '2x1', '3x1', '4x1', '1x2', '2x2')
# Text sizes: the most and least a tile's name and value may be, an on or off's most, and the least an auto tile's
# value may be in one cell before it's two
NAME_SIZES = (20, 14)
VALUE_SIZES = (48, 16)
STATE_SIZE = 24
AUTO_LEAST = 22
LINE_GAP = 4
# How long a press is held to open a light's brightness
LONG_PRESS = 0.6
SLIDER_HEIGHT = 96
# The entities a tile can be, and which of them toggle
DOMAINS = ('light', 'switch', 'sensor', 'binary_sensor')
TOGGLES = ('light', 'switch')
MOST_TILES = 12
MOST_PAGES = 6


class Page:
    def __init__(self, name, tiles):
        self.name, self.tiles = name, list(tiles)[:MOST_TILES]


def brightness_percent(brightness):
    """Home Assistant's brightness (0-255) as a percentage, at least 1 for a light that's on."""
    return max(1, round(brightness * 100 / 255))


def ago(text, now):
    """An ISO time (a timestamp sensor's state) as how long before now it was, or None if it isn't one."""
    try:
        then = datetime.fromisoformat(text)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = now - then.timestamp()
    if seconds < -60:
        return time.strftime('%d %b %H:%M', time.localtime(then.timestamp()))
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return '{} min ago'.format(int(seconds // 60))
    if seconds < 86400:
        return '{} h ago'.format(int(seconds // 3600))
    if seconds < 7 * 86400:
        return '{} days ago'.format(int(seconds // 86400)) if seconds >= 2 * 86400 else 'yesterday'
    return time.strftime('%d %b', time.localtime(then.timestamp()))


class Tile:
    """A Home Assistant entity on the screen. name: the page's own for it, or None for Home Assistant's; size: one of
    SIZES."""

    def __init__(self, entity_id, name=None, size='auto'):
        self.entity_id = entity_id
        self.domain = entity_id.split('.', 1)[0]
        self.name = name
        self.size = size if size in SIZES else 'auto'
        self.span = (1, 1)  # the cells it has, across and down
        self.box = None  # None when it doesn't fit

    def look(self, state, now=None):
        """(title, what it shows, whether it's on, whether Home Assistant has it) for its state ({"state",
        "attributes"}, or None when it isn't known)."""
        attributes = (state or {}).get('attributes') or {}
        title = self.name or attributes.get('friendly_name') or self.entity_id
        value = (state or {}).get('state')
        if value is None or value in ('unavailable', 'unknown'):
            return title, 'Unavailable' if value == 'unavailable' else '—', False, False
        if self.domain in TOGGLES or self.domain == 'binary_sensor':
            on = value == 'on'
            text = 'On' if on else 'Off'
            if on and self.domain == 'light' and attributes.get('brightness') is not None:
                text += ' · {}%'.format(brightness_percent(attributes['brightness']))
            return title, text, on, True
        if attributes.get('device_class') == 'timestamp':
            when = ago(value, time.time() if now is None else now)
            if when:
                return title, when, False, True
        unit = attributes.get('unit_of_measurement')
        return title, value + (' ' + unit if unit else ''), False, True

    def toggles(self):
        return self.domain in TOGGLES

    def dims(self, state):
        """Whether its brightness can be set (a light that has one)."""
        modes = ((state or {}).get('attributes') or {}).get('supported_color_modes') or []
        return self.domain == 'light' and any(mode != 'onoff' for mode in modes)

    def shows_time(self, state):
        return ((state or {}).get('attributes') or {}).get('device_class') == 'timestamp'

    def says_more(self):
        """Whether its value can be long (a sensor's), not only on or off."""
        return not (self.toggles() or self.domain == 'binary_sensor')


def cells(width, height):
    """(columns, rows) of the grid in width x height: as many cells as come closest to CELL."""
    return (max(1, round((width + GAP) / (CELL[0] + GAP))), max(1, round((height + GAP) / (CELL[1] + GAP))))


def place(free, across, down):
    """The first (column, row) where a tile across x down fits in free (rows of whether each cell is), or None."""
    for row in range(len(free) - down + 1):
        for column in range(len(free[0]) - across + 1):
            if all(free[r][c] for r in range(row, row + down) for c in range(column, column + across)):
                return column, row
    return None


class Panel:
    """The screen's picture. state(entity_id) gives an entity's state (None when it isn't known); tapped(tile) and
    brightness(tile, percent) act on Home Assistant. The screen may have a backlight (on(), off())."""

    def __init__(self, screen, state=lambda entity_id: None, tapped=lambda tile: None,
                 brightness=lambda tile, percent: None, now=time.localtime, clock=time.monotonic):
        self.screen, self.state, self.tapped, self.brightness = screen, state, tapped, brightness
        self.now, self.clock = now, clock
        self.width, self.height = screen.size
        self.image = Image.new('RGB', screen.size, BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)
        self._fonts = {}
        self.pages = []
        self.page = 0
        self.tiles = []  # the page's that fit on the screen
        self.left_out = 0  # how many of them don't
        self.grid = (1, 1)
        self.cell_width = 0
        self.tabs = []  # each page's tab in the bar: (left, right), with more than one page
        self.start = None  # where the touch went down, for a swipe
        self.swiping = False
        self.pressed = None
        self.held = None  # the long press's timer
        self.adjusting = None  # the tile whose brightness is open
        self.level = None  # its brightness, as dragged
        # A touch on the slider (dragging), or off it (a tap there closes it)
        self.dragging = self.outside = False
        self.minute = None
        # What's wrong (Home Assistant not connected), shown in the bar, or None
        self.status = None
        self.hint = None  # shown where the tiles go when there are none
        self.shown = False
        # The screen goes dark after timeout seconds untouched (0: never); a touch on a dark screen only wakes it
        self.timeout = 0
        self.touched_at = clock()
        self.awake = True
        self.waking = False  # the touch that woke it, until it lifts

    def font(self, size):
        if size not in self._fonts:
            self._fonts[size] = ImageFont.load_default(size)
        return self._fonts[size]

    def set_pages(self, pages, hint=None):
        """The pages (Page), shown from the first; hint is shown when they have no tiles."""
        self.pages, self.hint = list(pages)[:MOST_PAGES] or [Page('', [])], hint
        self.go_to(0)

    def set_tiles(self, tiles, hint=None):
        """One page of tiles."""
        self.set_pages([Page('', tiles)], hint)

    def go_to(self, page):
        self.page = page
        self.pressed = self.adjusting = None
        self.cancel_hold()
        self.layout()
        if self.shown:
            self.show_all()

    def layout(self):
        """Each of the page's tiles in the first place in the grid it fits, across then down."""
        top = BAR_HEIGHT + MARGIN
        width, height = self.width - 2 * MARGIN, self.height - MARGIN - top
        columns, rows = self.grid = cells(width, height)
        cell_width = self.cell_width = (width - (columns - 1) * GAP) / columns
        cell_height = (height - (rows - 1) * GAP) / rows
        free = [[True] * columns for _ in range(rows)]
        tiles = self.pages[self.page].tiles
        self.tiles = []
        for tile in tiles:
            tile.span = self.wanted(tile)
            spot = place(free, *tile.span)
            if spot is None:
                tile.box = None
                continue
            (column, row), (across, down) = spot, tile.span
            for r in range(row, row + down):
                for c in range(column, column + across):
                    free[r][c] = False
            tile.box = (MARGIN + round(column * (cell_width + GAP)), top + round(row * (cell_height + GAP)),
                        MARGIN + round((column + across) * (cell_width + GAP) - GAP),
                        top + round((row + down) * (cell_height + GAP) - GAP))
            self.tiles.append(tile)
        self.left_out = len(tiles) - len(self.tiles)

    def wanted(self, tile):
        """The cells a tile wants (across, down), no more than the grid has: its size, or for 'auto' one cell, or two
        across when its value wouldn't fit in one at AUTO_LEAST in two lines."""
        if tile.size != 'auto':
            across, down = (int(n) for n in tile.size.split('x'))
        else:
            _, value, _, available = tile.look(self.state(tile.entity_id))
            fits = not (tile.says_more() and available) or self.wrapped(
                value, self.cell_width - 2 * PADDING, 2, (AUTO_LEAST, AUTO_LEAST), shorten=False)
            across, down = (1, 1) if fits else (2, 1)
        return min(across, self.grid[0]), min(down, self.grid[1])

    def tile_at(self, x, y):
        return next((tile for tile in self.tiles
                     if tile.box[0] <= x < tile.box[2] and tile.box[1] <= y < tile.box[3]), None)

    # Text that fits

    def wrapped(self, text, width, lines, sizes, shorten=True):
        """(font, lines of text) for text in width: the largest size from sizes[0] down to sizes[1] that fits in that
        many lines with every word whole; failing that, with words broken where they join (CounterTopLeft at its
        capitals, sonoff_snzb at the underscore), then anywhere; failing that, the smallest with the last line
        shortened (or None, without shorten)."""
        for breaking in (None, 'joins', 'anywhere'):
            for size in range(sizes[0], sizes[1] - 1, -2):
                font = self.font(size)
                split = self.split(text, font, width, breaking)
                if split is not None and len(split) <= lines:
                    return font, split
        if not shorten:
            return None
        font = self.font(sizes[1])
        split = self.split(text, font, width, 'anywhere')
        return font, split[:lines - 1] + [self.shortened(' '.join(split[lines - 1:]), font, width)]

    def fitted(self, text, width, height, sizes, most_lines):
        """(font, lines) for text in width x height, in up to most_lines lines: whichever number of lines lets it be
        largest (sizes as wrapped has them), or the smallest with the last line shortened."""
        best = None
        for lines in range(1, most_lines + 1):
            largest = min(sizes[0], (height - (lines - 1) * LINE_GAP) // lines)
            if largest < sizes[1]:
                break
            found = self.wrapped(text, width, lines, (largest, sizes[1]), shorten=False)
            if found and (best is None or found[0].size > best[0].size):
                best = found
        room = max(1, min(most_lines, (height + LINE_GAP) // (sizes[1] + LINE_GAP)))
        return best or self.wrapped(text, width, room, (sizes[1], sizes[1]))

    def split(self, text, font, width, breaking='anywhere'):
        """text in lines no wider than width, at spaces. A word too long for a line on its own is broken as breaking
        says ('joins' or 'anywhere'), or with None the answer is None."""
        lines, line = [], ''
        for word in text.split():
            trial = (line + ' ' + word).strip()
            if self.draw.textlength(trial, font=font) <= width:
                line = trial
                continue
            if line:
                lines.append(line)
            while self.draw.textlength(word, font=font) > width and len(word) > 1:
                if breaking is None:
                    return None
                cut = self.cut(word, font, width, breaking)
                if cut is None:
                    return None
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        if line:
            lines.append(line)
        return lines or ['']

    def cut(self, word, font, width, breaking):
        """Where to break a word too wide for width: the last join (a capital after a small letter, or after _ or -)
        that leaves a part that fits, or with 'anywhere' the last letter that does; None if there's none."""
        if breaking == 'joins':
            joins = [i for i in range(1, len(word))
                     if (word[i].isupper() and word[i - 1].islower()) or word[i - 1] in '_-']
        else:
            joins = range(1, len(word))
        fitting = [i for i in joins if self.draw.textlength(word[:i], font=font) <= width]
        return fitting[-1] if fitting else (None if breaking == 'joins' else 1)

    def shortened(self, text, font, width):
        if self.draw.textlength(text, font=font) <= width:
            return text
        while text and self.draw.textlength(text + '…', font=font) > width:
            text = text[:-1]
        return text.rstrip() + '…'

    # Drawing

    def draw_bar(self):
        box = (0, 0, self.width, BAR_HEIGHT)
        now = self.now()
        self.minute = (now.tm_hour, now.tm_min)
        middle = BAR_HEIGHT // 2
        self.draw.rectangle(box, fill=BAR)
        clock = time.strftime('%H:%M', now)
        self.draw.text((self.width - MARGIN, middle), clock, font=self.font(26), fill=TEXT, anchor='rm')
        right = self.width - 2 * MARGIN - self.draw.textlength(clock, font=self.font(26))
        left = MARGIN
        self.tabs = []
        if len(self.pages) > 1:
            # A tab for each page, the shown one marked; their names shortened to share the room
            font = self.font(20)
            share = (right - left) // len(self.pages) - 2 * TAB_PADDING - 4
            for index, page in enumerate(self.pages):
                name = self.shortened(page.name or 'Page {}'.format(index + 1), font, max(share, 24))
                width = self.draw.textlength(name, font=font) + 2 * TAB_PADDING
                if index == self.page:
                    self.draw.rounded_rectangle((left, 6, left + width, BAR_HEIGHT - 7), radius=12, fill=TILE)
                self.draw.text((left + TAB_PADDING, middle), name, font=font,
                               fill=TEXT if index == self.page else MUTED, anchor='lm')
                self.tabs.append((left, left + width))
                left += width + 4
            left += MARGIN
            text, colour = self.warning(), WARNING  # the date makes way for the tabs
        elif self.warning():
            text, colour = self.warning(), WARNING
        else:
            text, colour = time.strftime('%A %d %B', now), MUTED
        if text and right - left > 40:
            self.draw.text((left, middle), self.shortened(text, self.font(20), right - left), font=self.font(20),
                           fill=colour, anchor='lm')
        return box

    def warning(self):
        """What's wrong, for the bar: Home Assistant's, or tiles that don't fit; or None."""
        if self.status or not self.left_out:
            return self.status
        return "1 tile doesn't fit" if self.left_out == 1 else "{} tiles don't fit".format(self.left_out)

    def draw_tile(self, tile):
        left, top, right, bottom = tile.box
        state = self.state(tile.entity_id)
        title, value, on, available = tile.look(state)
        if on:
            fill, band, text, muted = TILE_ON, BAND_ON, TEXT_ON, TEXT_ON
        else:
            fill, band, text, muted = TILE, BAND, TEXT if available else MUTED, TEXT if available else FAINT
        if tile is self.pressed:
            fill, band = (tuple(min(255, c + PRESSED) for c in colour) for colour in (fill, band))
        inside = right - left - 2 * PADDING
        self.draw.rectangle(tile.box, fill=BACKGROUND)
        self.draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS, fill=fill)

        # The name, in a band across the top: one line if it fits, or two
        font, lines = self.wrapped(title, inside, 2, NAME_SIZES)
        below = top + 2 * BAND_PADDING + len(lines) * font.size + (len(lines) - 1) * 3
        self.draw.rounded_rectangle((left, top, right - 1, below), radius=RADIUS, fill=band,
                                    corners=(True, True, False, False))
        y = top + BAND_PADDING
        for line in lines:
            self.draw.text((left + PADDING, y), line, font=font, fill=text)
            y += font.size + 3

        # The value, sized to what's below: one line for on or off, a sensor's onto more when it's long
        height = bottom - below - 2 * PADDING
        if tile.says_more() and available:
            font, lines = self.fitted(value, inside, height, VALUE_SIZES, 3)
        else:
            font, lines = self.fitted(value, inside, height, (STATE_SIZE, VALUE_SIZES[1]), 1)
        y = bottom - PADDING - (len(lines) - 1) * (font.size + LINE_GAP)
        for line in lines:
            self.draw.text((left + PADDING, y), line, font=font, fill=muted, anchor='ls')
            y += font.size + LINE_GAP
        return tile.box

    def draw_hint(self):
        if self.hint and not self.tiles:
            self.draw.text((self.width // 2, (BAR_HEIGHT + self.height) // 2), self.hint, font=self.font(24),
                           fill=MUTED, anchor='mm')

    def slider_box(self):
        top = (BAR_HEIGHT + self.height - SLIDER_HEIGHT) // 2
        return (MARGIN * 3, top, self.width - MARGIN * 3, top + SLIDER_HEIGHT)

    def draw_brightness(self):
        """The open brightness: its tile's name, and the slider filled to the level."""
        area = (0, BAR_HEIGHT, self.width, self.height)
        left, top, right, bottom = self.slider_box()
        self.draw.rectangle(area, fill=BACKGROUND)
        title = self.adjusting.look(self.state(self.adjusting.entity_id))[0]
        self.draw.text((self.width // 2, top - 40), self.shortened(title, self.font(28), right - left),
                       font=self.font(28), fill=TEXT, anchor='mm')
        self.draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS, fill=TILE)
        filled = left + (right - left) * self.level // 100
        if filled > left:
            self.draw.rounded_rectangle((left, top, max(filled, left + 2 * RADIUS) - 1, bottom - 1), radius=RADIUS,
                                        fill=TILE_ON)
        self.draw.text((self.width // 2, bottom + 40), '{}%  ·  tap outside the bar to close'.format(self.level),
                       font=self.font(20), fill=MUTED, anchor='mm')
        return area

    def show_all(self):
        self.draw.rectangle((0, 0, self.width, self.height), fill=BACKGROUND)
        self.draw_bar()
        if self.adjusting:
            self.draw_brightness()
        else:
            for tile in self.tiles:
                self.draw_tile(tile)
            self.draw_hint()
        self.screen.show(self.image)
        self.shown = True

    def set_status(self, status):
        if status != self.status:
            self.status = status
            if self.shown:
                self.screen.show(self.image, self.draw_bar())

    def changed(self, entity_ids):
        """Home Assistant's states changed: those entities' (None: all)."""
        if not self.shown:
            return
        if self.adjusting:
            if entity_ids is None or self.adjusting.entity_id in entity_ids:
                if not self.adjusting.dims(self.state(self.adjusting.entity_id)):
                    self.close_brightness()
            return
        shown = [tile for tile in self.pages[self.page].tiles if entity_ids is None or tile.entity_id in entity_ids]
        if any(tile.size == 'auto' and self.wanted(tile) != tile.span for tile in shown):
            # An auto tile's value is now longer or shorter than one cell has room for
            self.layout()
            self.show_all()
            return
        for tile in shown:
            if tile.box:
                self.screen.show(self.image, self.draw_tile(tile))

    # Touches

    def touched(self, kind, x, y):
        """A touch from the screen: ('down' | 'move' | 'up', x, y)."""
        self.touched_at = self.clock()
        if not self.awake or self.waking:
            # The touch that wakes the screen does nothing else
            if not self.awake:
                self.wake()
                self.waking = True
            if kind == 'up':
                self.waking = False
            return
        if self.adjusting:
            self.touched_brightness(kind, x, y)
        elif kind == 'down':
            self.start, self.swiping = (x, y), False
            self.pressed = self.tile_at(x, y)
            if self.pressed and self.pressed.toggles():
                self.screen.show(self.image, self.draw_tile(self.pressed))
                if self.pressed.dims(self.state(self.pressed.entity_id)):
                    self.held = asyncio.get_running_loop().call_later(LONG_PRESS, self.open_brightness, self.pressed)
            else:
                self.pressed = None
        elif kind == 'move':
            if self.start and len(self.pages) > 1 and abs(x - self.start[0]) > SWIPE_START:
                self.swiping = True  # across the screen: a swipe, not a press
                self.unpress()
            elif self.pressed and self.tile_at(x, y) is not self.pressed:
                self.cancel_hold()
        elif kind == 'up':
            start, self.start = self.start, None
            if self.swiping:
                self.swiping = False
                across = x - start[0]
                if abs(across) >= SWIPE and abs(y - start[1]) < abs(across):
                    page = min(max(self.page + (1 if across < 0 else -1), 0), len(self.pages) - 1)
                    if page != self.page:
                        self.go_to(page)
            elif self.pressed:
                tile, self.pressed = self.pressed, None
                self.cancel_hold()
                self.screen.show(self.image, self.draw_tile(tile))
                if self.tile_at(x, y) is tile:
                    self.tapped(tile)
            elif start and y < BAR_HEIGHT and start[1] < BAR_HEIGHT:
                tab = self.tab_at(x)
                if tab is not None and tab == self.tab_at(start[0]) and tab != self.page:
                    self.go_to(tab)

    def tab_at(self, x):
        return next((index for index, (left, right) in enumerate(self.tabs) if left <= x < right), None)

    def unpress(self):
        self.cancel_hold()
        if self.pressed:
            tile, self.pressed = self.pressed, None
            self.screen.show(self.image, self.draw_tile(tile))

    def cancel_hold(self):
        if self.held:
            self.held.cancel()
            self.held = None

    def open_brightness(self, tile):
        self.held = None
        self.pressed = None
        self.adjusting = tile
        attributes = (self.state(tile.entity_id) or {}).get('attributes') or {}
        self.level = brightness_percent(attributes['brightness']) if attributes.get('brightness') else 0
        self.dragging = self.outside = False
        self.show_all()

    def close_brightness(self):
        self.adjusting = None
        self.show_all()

    def touched_brightness(self, kind, x, y):
        left, top, right, bottom = self.slider_box()
        on_slider = left - MARGIN <= x < right + MARGIN and top - MARGIN <= y < bottom + MARGIN
        if kind == 'down':
            # The finger that opened it is still down: its lifting isn't a tap off the slider
            self.dragging = on_slider
            self.outside = not on_slider
        if kind in ('down', 'move') and self.dragging:
            level = min(100, max(0, round((x - left) * 100 / (right - left))))
            if level != self.level:
                self.level = level
                self.screen.show(self.image, self.draw_brightness())
        elif kind == 'up':
            if self.dragging:
                self.dragging = False
                self.brightness(self.adjusting, self.level)
            elif self.outside:
                self.close_brightness()

    # The screen going dark, and waking

    def sleep(self):
        self.awake = False
        self.cancel_hold()
        self.pressed = None
        if self.adjusting:
            self.adjusting = None
            self.show_all()
        backlight = getattr(self.screen, 'backlight', None)
        if backlight:
            backlight.off()

    def wake(self):
        self.awake = True
        backlight = getattr(self.screen, 'backlight', None)
        if backlight:
            backlight.on()

    def tick(self):
        """Once a second: the bar when the minute changes (and the tiles that show how long ago), and the screen
        going dark."""
        now = self.now()
        if (now.tm_hour, now.tm_min) != self.minute:
            self.screen.show(self.image, self.draw_bar())
            if not self.adjusting:
                for tile in self.tiles:
                    if tile.shows_time(self.state(tile.entity_id)):
                        self.screen.show(self.image, self.draw_tile(tile))
        if self.awake and self.timeout and self.clock() - self.touched_at >= self.timeout:
            self.sleep()

    async def run(self):
        self.show_all()
        while True:
            self.tick()
            await asyncio.sleep(1)
