"""What the screen shows: the clock at the top, the tiles in a grid below it (as many across as fit: four in
landscape, two in portrait), and a line at the bottom when something's wrong.

Each tile is a Home Assistant entity, chosen on the page: a light or switch (a tap toggles it; a light's long press
opens its brightness), or a sensor (its state and unit). A touch shows at once on the tile it's on, and a tap (lifted
on the same tile) acts. Only what changed is drawn again: a tile, or the clock when the minute changes. Home Assistant
answers a tap with the entity's new state, which redraws the tile.

The brightness is a bar across the screen, over the tiles: dragging along it sets the brightness (sent when the
finger lifts), and a tap off it closes it.
"""
import asyncio
import time

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (18, 20, 26)
TEXT = (235, 235, 240)
MUTED = (150, 155, 170)
FAINT = (90, 95, 110)
TILE = (44, 48, 60)
TILE_ON = (250, 190, 70)
TEXT_ON = (24, 22, 18)
WARNING = (240, 150, 90)
# How much lighter a tile is while it's touched
PRESSED = 40
MARGIN = 16
GAP = 12
CLOCK_HEIGHT = 120
TILE_WIDTH = 180  # at least: the columns are as many as fit
TILE_HEIGHT = 120
RADIUS = 18
STATUS_HEIGHT = 36
# How long a press is held to open a light's brightness
LONG_PRESS = 0.6
BAR_HEIGHT = 96
# The entities a tile can be, and which of them toggle
DOMAINS = ('light', 'switch', 'sensor', 'binary_sensor')
TOGGLES = ('light', 'switch')
MOST_TILES = 8


class Tile:
    """A Home Assistant entity on the screen. name: the page's own for it, or None for Home Assistant's."""

    def __init__(self, entity_id, name=None):
        self.entity_id = entity_id
        self.domain = entity_id.split('.', 1)[0]
        self.name = name
        self.box = None

    def look(self, state):
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
        unit = attributes.get('unit_of_measurement')
        return title, value + (' ' + unit if unit else ''), False, True

    def toggles(self):
        return self.domain in TOGGLES

    def dims(self, state):
        """Whether its brightness can be set (a light that has one)."""
        modes = ((state or {}).get('attributes') or {}).get('supported_color_modes') or []
        return self.domain == 'light' and any(mode != 'onoff' for mode in modes)


def brightness_percent(brightness):
    """Home Assistant's brightness (0-255) as a percentage, at least 1 for a light that's on."""
    return max(1, round(brightness * 100 / 255))


def fitted(draw, text, font, width):
    """text, shortened with an ellipsis to fit width."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + '…', font=font) > width:
        text = text[:-1]
    return text.rstrip() + '…'


class Panel:
    """The screen's picture. state(entity_id) gives an entity's state (None when it isn't known); tapped(tile) and
    brightness(tile, percent) act on Home Assistant."""

    def __init__(self, screen, state=lambda entity_id: None, tapped=lambda tile: None,
                 brightness=lambda tile, percent: None, now=time.localtime):
        self.screen, self.state, self.tapped, self.brightness, self.now = screen, state, tapped, brightness, now
        self.width, self.height = screen.size
        self.image = Image.new('RGB', screen.size, BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = {size: ImageFont.load_default(size) for size in (20, 24, 28, 40, 72)}
        self.tiles = []
        self.pressed = None
        self.held = None  # the long press's timer
        self.adjusting = None  # the tile whose brightness is open
        self.level = None  # its brightness, as dragged
        # A touch on the bar (dragging), or off it (a tap there closes it)
        self.dragging = self.outside = False
        self.minute = None
        # A line at the bottom saying what's wrong (Home Assistant not connected), or None
        self.status = None
        self.hint = None  # shown where the tiles go when there are none
        self.shown = False

    def set_tiles(self, tiles, hint=None):
        self.tiles, self.hint = list(tiles)[:MOST_TILES], hint
        self.pressed = self.adjusting = None
        self.layout()
        if self.shown:
            self.show_all()

    def layout(self):
        columns = max(1, (self.width - 2 * MARGIN + GAP) // (TILE_WIDTH + GAP))
        width = (self.width - 2 * MARGIN - (columns - 1) * GAP) // columns
        for index, tile in enumerate(self.tiles):
            row, column = divmod(index, columns)
            left = MARGIN + column * (width + GAP)
            top = CLOCK_HEIGHT + MARGIN + row * (TILE_HEIGHT + GAP)
            tile.box = (left, top, left + width, top + TILE_HEIGHT)

    def tile_at(self, x, y):
        return next((tile for tile in self.tiles
                     if tile.box[0] <= x < tile.box[2] and tile.box[1] <= y < tile.box[3]), None)

    def draw_clock(self):
        box = (0, 0, self.width, CLOCK_HEIGHT)
        now = self.now()
        self.minute = (now.tm_hour, now.tm_min)
        self.draw.rectangle(box, fill=BACKGROUND)
        self.draw.text((self.width // 2, 58), time.strftime('%H:%M', now), font=self.fonts[72], fill=TEXT, anchor='mm')
        self.draw.text((self.width // 2, 106), time.strftime('%A %d %B', now), font=self.fonts[20], fill=MUTED,
                       anchor='mm')
        return box

    def draw_tile(self, tile):
        left, top, right, bottom = tile.box
        title, value, on, available = tile.look(self.state(tile.entity_id))
        if on:
            fill, text, muted = TILE_ON, TEXT_ON, TEXT_ON
        else:
            fill, text, muted = TILE, TEXT if available else MUTED, MUTED if available else FAINT
        if tile is self.pressed:
            fill = tuple(min(255, c + PRESSED) for c in fill)
        inside = right - left - 40
        self.draw.rectangle(tile.box, fill=BACKGROUND)
        self.draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS, fill=fill)
        self.draw.text((left + 20, top + 20), fitted(self.draw, title, self.fonts[24], inside), font=self.fonts[24],
                       fill=text)
        # A sensor's value is what matters: larger
        font = self.fonts[40] if not tile.toggles() and tile.domain != 'binary_sensor' and available else self.fonts[20]
        self.draw.text((left + 20, bottom - 18), fitted(self.draw, value, font, inside), font=font, fill=muted,
                       anchor='ls')
        return tile.box

    def draw_status(self):
        box = (0, self.height - STATUS_HEIGHT, self.width, self.height)
        self.draw.rectangle(box, fill=BACKGROUND)
        if self.status:
            self.draw.text((self.width // 2, self.height - STATUS_HEIGHT // 2), self.status, font=self.fonts[20],
                           fill=WARNING, anchor='mm')
        return box

    def draw_hint(self):
        if self.hint and not self.tiles:
            self.draw.text((self.width // 2, (CLOCK_HEIGHT + self.height - STATUS_HEIGHT) // 2), self.hint,
                           font=self.fonts[24], fill=MUTED, anchor='mm')

    def bar_box(self):
        top = (CLOCK_HEIGHT + self.height - STATUS_HEIGHT - BAR_HEIGHT) // 2
        return (MARGIN * 2, top, self.width - MARGIN * 2, top + BAR_HEIGHT)

    def draw_brightness(self):
        """The open brightness: its tile's name, and the bar filled to the level."""
        area = (0, CLOCK_HEIGHT, self.width, self.height - STATUS_HEIGHT)
        left, top, right, bottom = self.bar_box()
        self.draw.rectangle(area, fill=BACKGROUND)
        title = self.adjusting.look(self.state(self.adjusting.entity_id))[0]
        self.draw.text((self.width // 2, top - 40), fitted(self.draw, title, self.fonts[28], right - left),
                       font=self.fonts[28], fill=TEXT, anchor='mm')
        self.draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS, fill=TILE)
        filled = left + (right - left) * self.level // 100
        if filled > left:
            self.draw.rounded_rectangle((left, top, max(filled, left + 2 * RADIUS) - 1, bottom - 1), radius=RADIUS,
                                        fill=TILE_ON)
        self.draw.text((self.width // 2, bottom + 40), '{}%  ·  tap outside the bar to close'.format(self.level),
                       font=self.fonts[20], fill=MUTED, anchor='mm')
        return area

    def show_all(self):
        self.draw.rectangle((0, 0, self.width, self.height), fill=BACKGROUND)
        self.draw_clock()
        if self.adjusting:
            self.draw_brightness()
        else:
            for tile in self.tiles:
                self.draw_tile(tile)
            self.draw_hint()
        self.draw_status()
        self.screen.show(self.image)
        self.shown = True

    def set_status(self, status):
        if status != self.status:
            self.status = status
            if self.shown:
                self.screen.show(self.image, self.draw_status())

    def changed(self, entity_ids):
        """Home Assistant's states changed: those entities' (None: all)."""
        if not self.shown:
            return
        if self.adjusting:
            if entity_ids is None or self.adjusting.entity_id in entity_ids:
                if not self.adjusting.dims(self.state(self.adjusting.entity_id)):
                    self.close_brightness()
            return
        for tile in self.tiles:
            if entity_ids is None or tile.entity_id in entity_ids:
                self.screen.show(self.image, self.draw_tile(tile))

    def touched(self, kind, x, y):
        """A touch from the screen: ('down' | 'move' | 'up', x, y)."""
        if self.adjusting:
            self.touched_brightness(kind, x, y)
        elif kind == 'down':
            self.pressed = self.tile_at(x, y)
            if self.pressed and self.pressed.toggles():
                self.screen.show(self.image, self.draw_tile(self.pressed))
                if self.pressed.dims(self.state(self.pressed.entity_id)):
                    self.held = asyncio.get_running_loop().call_later(LONG_PRESS, self.open_brightness, self.pressed)
            else:
                self.pressed = None
        elif kind == 'move' and self.pressed and self.tile_at(x, y) is not self.pressed:
            self.cancel_hold()
        elif kind == 'up' and self.pressed:
            tile, self.pressed = self.pressed, None
            self.cancel_hold()
            self.screen.show(self.image, self.draw_tile(tile))
            if self.tile_at(x, y) is tile:
                self.tapped(tile)

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
        left, top, right, bottom = self.bar_box()
        on_bar = left - MARGIN <= x < right + MARGIN and top - MARGIN <= y < bottom + MARGIN
        if kind == 'down':
            # The finger that opened it is still down: its lifting isn't a tap off the bar
            self.dragging = on_bar
            self.outside = not on_bar
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

    async def run(self):
        self.show_all()
        while True:
            now = self.now()
            if (now.tm_hour, now.tm_min) != self.minute:
                self.screen.show(self.image, self.draw_clock())
            await asyncio.sleep(1)
