"""The screen on the Pi (screen.py): the framebuffer turned to match the display, RGB565, and touches from input
events, with a bytearray for the framebuffer and made-up events."""
import pytest
from PIL import Image

import screen

WIDTH, HEIGHT, PADDING = 8, 4, 6
STRIDE = WIDTH * 2 + PADDING


def test_rgb565_is_red_green_blue_in_5_6_5_bits_little_endian():
    image = Image.new('RGB', (4, 1))
    for x, colour in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]):
        image.putpixel((x, 0), colour)
    assert screen.rgb565(image) == b'\x00\xf8' + b'\xe0\x07' + b'\x1f\x00' + b'\xff\xff'


def where(rotation, x, y):
    """Where a point of the panel's picture is in the framebuffer, turned clockwise by rotation quarter turns."""
    return [(x, y), (WIDTH - 1 - y, x), (WIDTH - 1 - x, HEIGHT - 1 - y), (y, HEIGHT - 1 - x)][rotation]


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_a_part_of_the_picture_goes_where_it_shows_turned_and_nothing_else_changes(rotation):
    memory = bytearray(b'\xaa' * STRIDE * HEIGHT)
    framebuffer = screen.Framebuffer(memory, WIDTH, HEIGHT, STRIDE, 16, rotation)
    assert framebuffer.size == ((WIDTH, HEIGHT) if rotation in (0, 180) else (HEIGHT, WIDTH))
    picture = Image.new('RGB', framebuffer.size)
    picture.putpixel((2, 1), (255, 0, 0))
    box = (1, 0, 3, 3)
    framebuffer.show(picture, box)

    region = {where(rotation // 90, x, y) for x in range(box[0], box[2]) for y in range(box[1], box[3])}
    for y in range(HEIGHT):
        for x in range(WIDTH):
            pixel = bytes(memory[y * STRIDE + x * 2:y * STRIDE + x * 2 + 2])
            if (x, y) == where(rotation // 90, 2, 1):
                assert pixel == b'\x00\xf8', 'the red point'
            elif (x, y) in region:
                assert pixel == b'\x00\x00', 'the rest of the box, black'
            else:
                assert pixel == b'\xaa\xaa', 'outside the box, untouched'
    assert memory[WIDTH * 2:STRIDE] == b'\xaa' * PADDING  # the end of the first line, past the screen


def events(*items):
    return b''.join(screen.EVENT.pack(0, 0, kind, code, value) for kind, code, value in items)


SYNC = (screen.EV_SYN, 0, 0)


def test_a_tap_and_a_drag_are_down_move_up():
    touches = screen.Touches((480, 800))
    data = events((screen.EV_ABS, screen.ABS_X, 10), (screen.EV_ABS, screen.ABS_Y, 20),
                  (screen.EV_KEY, screen.BTN_TOUCH, 1), SYNC,
                  (screen.EV_ABS, screen.ABS_X, 30), SYNC,
                  (screen.EV_KEY, screen.BTN_TOUCH, 0), SYNC)
    assert touches.feed(data) == [('down', 10, 20), ('move', 30, 20), ('up', 30, 20)]


def test_an_event_split_between_reads_is_kept_for_the_next():
    touches = screen.Touches((480, 800))
    data = events((screen.EV_ABS, screen.ABS_X, 5), (screen.EV_ABS, screen.ABS_Y, 6),
                  (screen.EV_KEY, screen.BTN_TOUCH, 1), SYNC)
    assert touches.feed(data[:20]) == []
    assert touches.feed(data[20:]) == [('down', 5, 6)]


def test_a_touch_off_the_edge_is_kept_on_the_screen():
    touches = screen.Touches((480, 800))
    data = events((screen.EV_ABS, screen.ABS_X, 900), (screen.EV_ABS, screen.ABS_Y, -3),
                  (screen.EV_KEY, screen.BTN_TOUCH, 1), SYNC)
    assert touches.feed(data) == [('down', 479, 0)]


def test_the_touch_screen_is_found_by_name(tmp_path, monkeypatch):
    devices = tmp_path / 'devices'
    devices.write_text('I: Bus=0000\nN: Name="vc4-hdmi"\nH: Handlers=kbd event0 \n\n'
                       'I: Bus=0018\nN: Name="10-0038 generic ft5x06 (79)"\nH: Handlers=mouse0 event2 \n\n')
    monkeypatch.setattr(screen, 'INPUT_DEVICES', devices)
    assert screen.touch_device() == '/dev/input/event2'
    devices.write_text('N: Name="vc4-hdmi"\nH: Handlers=kbd event0 \n')
    assert screen.touch_device() is None


@pytest.mark.parametrize('percent, level', [(100, 255), (50, 69), (10, 7), (5, 4)])
def test_the_brightness_follows_a_curve_so_half_looks_half_as_bright(tmp_path, percent, level):
    (tmp_path / 'max_brightness').write_text('255')
    screen.Backlight(tmp_path).set_brightness(percent)
    assert (tmp_path / 'brightness').read_text() == str(level)
