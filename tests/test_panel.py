"""What the screen shows (panel.py): the tiles' layout, a touch shown at once, a tap, and only what changed drawn
again, on a screen that records what it's shown."""
import time

import pytest

import panel


class Screen:
    def __init__(self, size):
        self.size = size
        self.shown = []

    def show(self, image, box=None):
        self.shown.append(box)


def make(size, count=5):
    screen = Screen(size)
    tiles = [panel.Tile(f'Tile {n}') for n in range(count)]
    return screen, tiles, panel.Panel(screen, tiles, now=lambda: time.struct_time((2026, 11, 1, 21, 30, 0, 6, 305, 0)))


@pytest.mark.parametrize('size, across', [((800, 480), 4), ((480, 800), 2)])
def test_as_many_tiles_across_as_fit_inside_the_screen(size, across):
    _, tiles, _ = make(size)
    tops = sorted({tile.box[1] for tile in tiles})
    assert sum(1 for tile in tiles if tile.box[1] == tops[0]) == across
    for tile in tiles:
        left, top, right, bottom = tile.box
        assert 0 <= left < right <= size[0] and panel.CLOCK_HEIGHT <= top < bottom <= size[1]
        assert right - left >= panel.TILE_WIDTH


def test_the_whole_screen_is_shown_first():
    screen, _, p = make((800, 480))
    p.show_all()
    assert screen.shown == [None]


def test_a_tap_shows_at_once_and_turns_the_tile_on_drawing_only_the_tile():
    screen, tiles, p = make((800, 480))
    x, y = tiles[1].box[0] + 5, tiles[1].box[1] + 5
    p.touched('down', x, y)
    assert screen.shown == [tiles[1].box] and p.pressed is tiles[1]
    p.touched('up', x + 3, y + 3)
    assert screen.shown == [tiles[1].box] * 2 and tiles[1].on and p.pressed is None


def test_lifting_off_the_tile_does_nothing_but_redraw_it():
    screen, tiles, p = make((800, 480))
    p.touched('down', tiles[0].box[0] + 5, tiles[0].box[1] + 5)
    p.touched('up', 799, 0)
    assert not tiles[0].on and screen.shown == [tiles[0].box] * 2


def test_a_touch_between_tiles_draws_nothing():
    screen, _, p = make((800, 480))
    p.touched('down', 2, 2)
    p.touched('up', 2, 2)
    assert screen.shown == []
