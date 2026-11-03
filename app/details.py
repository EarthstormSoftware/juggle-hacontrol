"""What a long press on a tile opens, over the tiles: a light's controls, or a sensor's history.

A light's has what it can do (Home Assistant's supported_color_modes and effect_list say): its brightness, its warmth
(a colour temperature), its colour (a hue), and its effects; and a button to switch it, and one to close. A slider
sets what it's dragged to when the finger lifts; an effect is set by a tap.

A sensor's history is a graph of its numbers (or a timeline of a binary sensor's on and off, or a list of a text
sensor's changes) over a time chosen by a tap: the tile's own, or an hour, six, a day or a week.

Either closes with its button or a tap where there's nothing.
"""
import colorsys
import math
import time

import charts
import kinds
from panel import (BACKGROUND, BAR_HEIGHT, MARGIN, MUTED, PRESSED, RADIUS, TEXT, TEXT_ON, TILE, TILE_ON,
                   brightness_percent)

HEADER = 52
BUTTON = 52
POWER = 110  # the on and off button's width
SLIDER = 56
ROW_GAP = 16
CHIP = 46
CHIP_GAP = 10
CHIP_PADDING = 16
EDGE = MARGIN * 3
# Colour modes with a colour (the rest: brightness, color_temp, white, onoff)
COLOUR_MODES = ('hs', 'xy', 'rgb', 'rgbw', 'rgbww')
WARMEST, COOLEST = 2000, 6500
# The times a history can be shown for, in hours
PERIODS = (1, 6, 24, 168)


def period_name(hours):
    return '{} h'.format(hours) if hours < 48 else '{} days'.format(hours // 24)


def kelvin_colour(kelvin):
    """About the colour of white light at kelvin (Tanner Helland's fit to the black body's)."""
    t = kelvin / 100
    red = 255 if t <= 66 else 329.7 * (t - 60) ** -0.1332
    green = 99.47 * math.log(t) - 161.1 if t <= 66 else 288.1 * (t - 60) ** -0.0755
    blue = 255 if t >= 66 else (0 if t <= 19 else 138.5 * math.log(t - 10) - 305.0)
    return tuple(int(min(255, max(0, c))) for c in (red, green, blue))


def hue_colour(hue):
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue / 360, 1, 1))


class Detail:
    """What both have: the panel they're on, the tile they're for, buttons, and closing."""

    def __init__(self, panel, tile):
        self.panel, self.tile = panel, tile
        self.down = None  # what the touch went down on; None for the finger that opened it
        self.buttons = []  # (box, what)

    @property
    def left(self):
        return EDGE

    @property
    def right(self):
        return self.panel.width - EDGE

    def state(self):
        return self.panel.state(self.tile.entity_id)

    def attributes(self):
        return (self.state() or {}).get('attributes') or {}

    def title(self):
        return self.tile.look(self.state())[0]

    def area(self):
        return 0, BAR_HEIGHT, self.panel.width, self.panel.height

    def show(self):
        self.panel.screen.show(self.panel.image, self.draw())

    def draw(self):
        """Draws it all on the panel's image and returns the box drawn."""
        self.buttons = []
        self.panel.draw.rectangle(self.area(), fill=BACKGROUND)
        self.draw_content()
        return self.area()

    def button(self, box, label, what, chosen=False, size=20):
        """A button (a rounded box with its label), remembered for touches."""
        d, font = self.panel.draw, self.panel.font(size)
        fill = TILE_ON if chosen else TILE
        if self.down == ('button', what):
            fill = tuple(min(255, c + PRESSED) for c in fill)
        d.rounded_rectangle((box[0], box[1], box[2] - 1, box[3] - 1), radius=12, fill=fill)
        x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        if what == 'close':  # a cross (Pillow's font has no ✕)
            arm = (box[2] - box[0]) // 6
            for ends in ((x - arm, y - arm, x + arm, y + arm), (x - arm, y + arm, x + arm, y - arm)):
                d.line(ends, fill=TEXT, width=3)
        else:
            d.text((x, y), self.panel.shortened(label, font, box[2] - box[0] - 16), font=font,
                   fill=TEXT_ON if chosen else TEXT, anchor='mm')
        self.buttons.append((box, what))

    def header(self, more='', kept=0):
        """The title along the top, what's given beside it, and the close button at the right; kept: room kept
        beside the close button."""
        d = self.panel.draw
        top = BAR_HEIGHT + 16
        self.button((self.right - BUTTON, top, self.right, top + BUTTON), 'Close', 'close')
        room = self.right - BUTTON - 16 - kept - self.left
        font = self.panel.font(28)
        if more:
            more_font = self.panel.font(24)
            more = self.panel.shortened(more, more_font, room // 2)
            d.text((self.right - BUTTON - 16, top + BUTTON // 2), more, font=more_font, fill=MUTED, anchor='rm')
            room -= int(d.textlength(more, font=more_font)) + 24
        d.text((self.left, top + BUTTON // 2), self.panel.shortened(self.title(), font, room), font=font, fill=TEXT,
               anchor='lm')
        return top + HEADER + 20

    def flow(self, labels, top, most_bottom):
        """Where buttons with those labels go, in rows from top, each as wide as its label: their boxes, as many as
        fit above most_bottom."""
        font = self.panel.font(20)
        x, y = self.left, top
        boxes = []
        for label in labels:
            width = min(int(self.panel.draw.textlength(label, font=font)) + 2 * CHIP_PADDING, self.right - self.left)
            if x + width > self.right:
                x, y = self.left, y + CHIP + CHIP_GAP
            if y + CHIP > most_bottom:
                break
            boxes.append((x, y, x + width, y + CHIP))
            x += width + CHIP_GAP
        return boxes

    def chips(self, top, chips, most_bottom):
        """chips (label, what, chosen) as buttons in rows from top, as many as fit above most_bottom."""
        for box, (label, what, chosen) in zip(self.flow([chip[0] for chip in chips], top, most_bottom), chips):
            self.button(box, label, what, chosen)

    def at(self, x, y):
        return next((what for box, what in self.buttons if box[0] <= x < box[2] and box[1] <= y < box[3]), None)

    def touched(self, kind, x, y):
        if kind == 'down':
            what = self.at(x, y)
            self.down = ('button', what) if what is not None else self.touched_down(x, y) or ('nothing',)
            if self.down[0] == 'button':
                self.show()
        elif kind == 'move':
            self.touched_move(x, y)
        elif kind == 'up' and self.down:
            down, self.down = self.down, None
            if down[0] == 'button':
                self.show()
                if self.at(x, y) == down[1]:
                    self.pressed(down[1])
            elif down[0] == 'nothing':
                if self.at(x, y) is None:
                    self.panel.close_detail()
            else:
                self.touched_up(down)

    def touched_down(self, x, y):
        return None

    def touched_move(self, x, y):
        pass

    def touched_up(self, down):
        pass

    def pressed(self, what):
        if what == 'close':
            self.panel.close_detail()

    def changed(self):
        """Its entity's state changed."""
        self.show()

    def tick(self):
        """Once a minute."""


class LightDetail(Detail):
    def __init__(self, panel, tile):
        super().__init__(panel, tile)
        self.sliders = []  # (box, what): 'brightness', 'warmth' or 'colour'
        self.values = {}  # what a slider was set to here, until Home Assistant says what it is
        self.sliding = None
        self.effects_from = 0  # with more effects than fit, the first shown

    @staticmethod
    def can(state):
        """What a light can do, from its state: a set of 'brightness', 'warmth', 'colour', 'effects'."""
        attributes = (state or {}).get('attributes') or {}
        modes = attributes.get('supported_color_modes') or []
        found = set()
        if any(mode != 'onoff' for mode in modes):
            found.add('brightness')
        if 'color_temp' in modes:
            found.add('warmth')
        if any(mode in COLOUR_MODES for mode in modes):
            found.add('colour')
        if attributes.get('effect_list'):
            found.add('effects')
        return found

    def kelvins(self):
        attributes = self.attributes()
        warmest = attributes.get('min_color_temp_kelvin') or WARMEST
        coolest = attributes.get('max_color_temp_kelvin') or COOLEST
        return (warmest, coolest) if coolest > warmest else (WARMEST, COOLEST)

    def value(self, what):
        """A slider's value: as set here, or as Home Assistant says, or None when it doesn't say (a light showing
        a colour has no warmth)."""
        if what in self.values:
            return self.values[what]
        state, attributes = self.state() or {}, self.attributes()
        if what == 'brightness':
            on = state.get('state') == 'on' and attributes.get('brightness')
            return brightness_percent(attributes['brightness']) if on else 0
        mode = attributes.get('color_mode')
        if what == 'warmth' and mode == 'color_temp':
            if attributes.get('color_temp_kelvin'):
                return attributes['color_temp_kelvin']
            if attributes.get('color_temp'):
                return round(1000000 / attributes['color_temp'])
        if what == 'colour' and mode in COLOUR_MODES and attributes.get('hs_color'):
            return attributes['hs_color'][0]
        return None

    def fraction(self, what, value):
        if what == 'brightness':
            return value / 100
        if what == 'warmth':
            warmest, coolest = self.kelvins()
            return (value - warmest) / (coolest - warmest)
        return value / 360

    def from_fraction(self, what, fraction):
        fraction = min(1, max(0, fraction))
        if what == 'brightness':
            return round(fraction * 100)
        if what == 'warmth':
            warmest, coolest = self.kelvins()
            return round((warmest + fraction * (coolest - warmest)) / 50) * 50
        return round(fraction * 360) % 360

    def draw_content(self):
        d = self.panel.draw
        on = (self.state() or {}).get('state') == 'on'
        top = self.header(kept=POWER + 16)
        self.button((self.right - BUTTON - 16 - POWER, BAR_HEIGHT + 16, self.right - BUTTON - 16,
                     BAR_HEIGHT + 16 + BUTTON), 'On' if on else 'Off', 'power', chosen=on, size=22)
        can = self.can(self.state())
        self.sliders = []
        for what in ('brightness', 'warmth', 'colour'):
            if what in can:
                box = (self.left, top, self.right, top + SLIDER)
                self.draw_slider(box, what)
                self.sliders.append((box, what))
                top += SLIDER + ROW_GAP
        if 'effects' in can:
            self.draw_effects(top + 4)
        if not can:
            d.text((self.left, top), 'It only switches on and off.', font=self.panel.font(20), fill=MUTED)

    def draw_slider(self, box, what):
        left, top, right, bottom = box
        width, height = right - left, bottom - top
        image, d = self.panel.image, self.panel.draw
        value = self.value(what)
        if what == 'brightness':
            d.rounded_rectangle((left, top, right - 1, bottom - 1), radius=RADIUS, fill=TILE)
            filled = left + round(width * value / 100)
            if filled > left:
                d.rounded_rectangle((left, top, max(filled, left + 2 * RADIUS) - 1, bottom - 1), radius=RADIUS,
                                    fill=TILE_ON)
            label = 'Brightness  {}%'.format(value)
            # Dark on the filled part, light on the rest
            width_of_label = self.panel.draw.textlength(label, font=self.panel.font(20))
            ink = TEXT_ON if filled >= left + 18 + width_of_label * 0.6 else TEXT
        else:
            colours = ([kelvin_colour(self.from_fraction('warmth', x / width)) for x in range(width)]
                       if what == 'warmth' else [hue_colour(x * 360 / width) for x in range(width)])
            strip = self.panel.strip(colours, height)
            image.paste(strip, (left, top), self.panel.rounded_mask(width, height, RADIUS))
            if what == 'warmth':
                label = 'Warmth' + ('  {} K'.format(value) if value is not None else '')
            else:
                label = 'Colour'
            ink = TEXT_ON
        if value is not None and what != 'brightness':
            x = left + round(width * min(1, max(0, self.fraction(what, value))))
            x = min(max(x, left + 6), right - 6)
            d.rounded_rectangle((x - 5, top - 4, x + 5, bottom + 3), radius=5, fill=TEXT, outline=BACKGROUND, width=2)
        d.text((left + 18, (top + bottom) // 2), label, font=self.panel.font(20), fill=ink, anchor='lm')

    def draw_effects(self, top):
        effects = list(self.attributes().get('effect_list') or [])
        chosen = self.attributes().get('effect')
        bottom = self.panel.height - 2 * MARGIN
        self.panel.draw.text((self.left, top), 'Effects', font=self.panel.font(18), fill=MUTED)
        top += 28
        start = self.effects_from if self.effects_from < len(effects) else 0
        chips = [(name, ('effect', name), name == chosen) for name in effects[start:]]
        shown = len(self.flow([chip[0] for chip in chips], top, bottom))
        if shown < len(chips) or start:
            # Not all fit: room is kept for More, which shows the next ones (and after the last, the first)
            more = ('More ›', 'more', False)
            while shown and len(self.flow([chip[0] for chip in chips[:shown] + [more]], top, bottom)) <= shown:
                shown -= 1
            chips = chips[:shown] + [more]
        self.shown_effects = shown
        self.chips(top, chips, bottom)

    def slider_at(self, x, y):
        return next((what for (left, top, right, bottom), what in self.sliders
                     if left - MARGIN <= x < right + MARGIN and top - MARGIN // 2 <= y < bottom + MARGIN // 2), None)

    def slide(self, what, x):
        box = next(box for box, found in self.sliders if found == what)
        value = self.from_fraction(what, (x - box[0]) / (box[2] - box[0]))
        if value != self.values.get(what):
            self.values[what] = value
            self.show()

    def touched_down(self, x, y):
        what = self.slider_at(x, y)
        if what:
            self.sliding = what
            self.slide(what, x)
            return ('slider', what)
        return None

    def touched_move(self, x, y):
        if self.sliding:
            self.slide(self.sliding, x)

    def touched_up(self, down):
        if down[0] == 'slider':
            what, self.sliding = down[1], None
            value = self.values.get(what)
            if value is None:
                return
            if what == 'brightness':
                self.panel.adjust(self.tile, {'brightness_pct': value})
            elif what == 'warmth':
                self.panel.adjust(self.tile, {'color_temp_kelvin': value})
            else:
                self.panel.adjust(self.tile, {'hs_color': [value, 100]})

    def pressed(self, what):
        if what == 'power':
            self.panel.tapped(self.tile)
        elif what == 'more':
            self.effects_from += self.shown_effects
            if self.effects_from >= len(self.attributes().get('effect_list') or []):
                self.effects_from = 0
            self.show()
        elif isinstance(what, tuple) and what[0] == 'effect':
            self.panel.adjust(self.tile, {'effect': what[1]})
        else:
            super().pressed(what)

    def changed(self):
        if not self.can(self.state()) and (self.state() or {}).get('state') in (None, 'unavailable', 'unknown'):
            self.panel.close_detail()
            return
        if self.sliding:
            return  # drawn as it's dragged; Home Assistant's comes after
        self.values = {}
        self.show()


class HistoryDetail(Detail):
    def __init__(self, panel, tile):
        super().__init__(panel, tile)
        self.hours = tile.hours

    def draw_content(self):
        value = self.tile.look(self.state())[1]
        top = self.header(value)
        periods = sorted(set(PERIODS) | {self.tile.hours})
        self.chips(top, [(period_name(hours), ('hours', hours), hours == self.hours) for hours in periods],
                   self.panel.height)
        top += CHIP + 24
        box = (self.left, top, self.right, self.panel.height - 2 * MARGIN)
        found = self.panel.history_for(self.tile.entity_id, self.hours)
        if found is None or (found.points is None and found.loading):
            self.say(box, 'Asking Home Assistant…')
        elif found.points is None:
            self.say(box, "Couldn't get its history from Home Assistant")
        else:
            end = self.panel.wall()
            start = end - self.hours * 3600
            if self.tile.domain == 'binary_sensor':
                self.draw_timeline(box, found.points, start, end)
            elif charts.numbers(found.points):
                self.draw_line(box, found.points, start, end)
            else:
                self.draw_changes(box, found.points)

    def say(self, box, text):
        self.panel.draw.text(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), text, font=self.panel.font(22),
                             fill=MUTED, anchor='mm')

    def time_labels(self, left, right, y, start, end):
        d, font = self.panel.draw, self.panel.font(16)
        style = '%a %H:%M' if self.hours >= 48 else '%H:%M'
        for fraction, anchor in ((0, 'la'), (0.5, 'ma'), (1, 'ra')):
            when = start + fraction * (end - start)
            text = 'now' if fraction == 1 else time.strftime(style, time.localtime(when))
            d.text((left + fraction * (right - left), y), text, font=font, fill=MUTED, anchor=anchor)

    def draw_line(self, box, points, start, end):
        d = self.panel.draw
        font = self.panel.font(16)
        unit = self.attributes().get('unit_of_measurement') or ''
        left, top, right, bottom = box
        values = [value for _, value in charts.numbers(points)]
        low, high = charts.value_range(values)
        labels = [self.number(low + (high - low) * n / 3) for n in range(4)]
        left += max(int(d.textlength(label, font=font)) for label in labels) + 12
        bottom -= 56
        for n, label in enumerate(labels):
            y = bottom - (bottom - top) * n / 3
            d.line((left, y, right, y), fill=TILE, width=1)
            d.text((left - 10, y), label, font=font, fill=MUTED, anchor='rm')
        charts.line(d, (left, top, right, bottom), points, start, end, TILE_ON, fill=(70, 62, 44), low=low, high=high,
                    width=3)
        self.time_labels(left, right, bottom + 8, start, end)
        summary = 'Least {}, most {}{}'.format(self.number(min(values)), self.number(max(values)),
                                               ' ' + unit if unit else '')
        d.text((left, bottom + 34), summary, font=self.panel.font(18), fill=TEXT)

    @staticmethod
    def number(value):
        return '{:g}'.format(round(value, 1 if abs(value) < 100 else 0))

    def draw_timeline(self, box, points, start, end):
        d = self.panel.draw
        left, top, right, bottom = box
        on_name, _ = kinds.on_off(kinds.device_class(self.state()))
        charts.timeline(d, (left, top, right, top + 64), points, start, end, TILE_ON, TILE, radius=RADIUS)
        self.time_labels(left, right, top + 72, start, end)
        spans = charts.spans(points, start, end)
        times = sum(1 for index, (since, _, state) in enumerate(spans)
                    if state == 'on' and (since > start or index > 0))
        lasts = [until for _, until, state in spans if state == 'on']
        y = top + 120
        font = self.panel.font(22)
        d.text((left, y), '{}: {} time{}'.format(on_name, times, '' if times == 1 else 's'), font=font, fill=TEXT)
        if lasts:
            last = lasts[-1]
            was = 'now' if last >= end - 1 else _ago(end - last)
            d.text((left, y + 36), 'Last {}: {}'.format(on_name.lower(), was), font=font, fill=MUTED)

    def draw_changes(self, box, points):
        """A text sensor's changes, the latest first, as many as fit."""
        d, font = self.panel.draw, self.panel.font(20)
        y = box[1]
        style = '%a %H:%M' if self.hours >= 24 else '%H:%M'
        for when, state in reversed(points):
            if y + 28 > box[3]:
                break
            d.text((box[0], y), time.strftime(style, time.localtime(when)), font=font, fill=MUTED)
            d.text((box[0] + 130, y), self.panel.shortened(str(state), font, box[2] - box[0] - 130), font=font,
                   fill=TEXT)
            y += 30

    def pressed(self, what):
        if isinstance(what, tuple) and what[0] == 'hours':
            self.hours = what[1]
            self.show()
        else:
            super().pressed(what)

    def tick(self):
        self.show()


def _ago(seconds):
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return '{} min ago'.format(int(seconds // 60))
    if seconds < 86400:
        return '{} h ago'.format(int(seconds // 3600))
    return '{} days ago'.format(int(seconds // 86400))
