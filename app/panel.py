"""What the screen shows: the clock at the top and the tiles in a grid below it, as many across as fit (four in
landscape, two in portrait). A touch shows at once on the tile it's on, and a tap (lifted on the same tile) acts.
Only what changed is drawn again: a tile, or the clock when the minute changes.

For now there's one tile, Test, which only turns itself on and off; Home Assistant's lights and sensors come next
(docs/roadmap.md).
"""
import asyncio
import time

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (18, 20, 26)
TEXT = (235, 235, 240)
MUTED = (150, 155, 170)
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


class Tile:
    """A square on the screen that can be tapped."""

    def __init__(self, name):
        self.name = name
        self.on = False
        self.box = None

    def tap(self):
        self.on = not self.on

    def state_text(self):
        return 'On' if self.on else 'Off'


class Panel:
    def __init__(self, screen, tiles, now=time.localtime):
        self.screen, self.tiles, self.now = screen, tiles, now
        self.width, self.height = screen.size
        self.image = Image.new('RGB', screen.size, BACKGROUND)
        self.draw = ImageDraw.Draw(self.image)
        self.fonts = {size: ImageFont.load_default(size) for size in (20, 28, 72)}
        self.pressed = None
        self.minute = None
        # A line at the bottom saying what's wrong (Home Assistant not connected), or None
        self.status = None
        self.shown = False
        self.layout()

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
        fill, text, state = (TILE_ON, TEXT_ON, TEXT_ON) if tile.on else (TILE, TEXT, MUTED)
        if tile is self.pressed:
            fill = tuple(min(255, c + PRESSED) for c in fill)
        self.draw.rectangle(tile.box, fill=BACKGROUND)
        self.draw.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS, fill=fill)
        self.draw.text((left + 20, top + 20), tile.name, font=self.fonts[28], fill=text)
        self.draw.text((left + 20, bottom - 20), tile.state_text(), font=self.fonts[20], fill=state, anchor='ls')
        return tile.box

    def draw_status(self):
        box = (0, self.height - STATUS_HEIGHT, self.width, self.height)
        self.draw.rectangle(box, fill=BACKGROUND)
        if self.status:
            self.draw.text((self.width // 2, self.height - STATUS_HEIGHT // 2), self.status, font=self.fonts[20],
                           fill=WARNING, anchor='mm')
        return box

    def set_status(self, status):
        if status != self.status:
            self.status = status
            if self.shown:
                self.screen.show(self.image, self.draw_status())

    def show_all(self):
        self.draw.rectangle((0, 0, self.width, self.height), fill=BACKGROUND)
        self.draw_clock()
        for tile in self.tiles:
            self.draw_tile(tile)
        self.draw_status()
        self.screen.show(self.image)
        self.shown = True

    def touched(self, kind, x, y):
        """A touch from the screen: ('down' | 'move' | 'up', x, y)."""
        if kind == 'down':
            self.pressed = self.tile_at(x, y)
            if self.pressed:
                self.screen.show(self.image, self.draw_tile(self.pressed))
        elif kind == 'up' and self.pressed:
            tile, self.pressed = self.pressed, None
            if self.tile_at(x, y) is tile:
                tile.tap()
            self.screen.show(self.image, self.draw_tile(tile))

    async def run(self):
        self.show_all()
        while True:
            now = self.now()
            if (now.tm_hour, now.tm_min) != self.minute:
                self.screen.show(self.image, self.draw_clock())
            await asyncio.sleep(1)
