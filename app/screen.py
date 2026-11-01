"""The touch screen: where the panel's pictures go and where touches come from (docs/roadmap.md, Drawing to the
screen).

On the Pi (Juggle OS, with "display" in app.json) the pictures go straight into the framebuffer, turned to match the
display's rotation (Juggle OS turns the console and the touch screen, but not the framebuffer), and touches come from
the touch screen's input device. On a PC, a window stands in for the screen and the mouse for a finger.

Pictures are Pillow images the size of the screen as the panel sees it (800x480 in landscape, 480x800 in portrait);
show() takes the part that changed, so a touch redraws only its tile.
"""
import asyncio
import mmap
import os
import struct
from pathlib import Path

from PIL import Image, ImageChops

FRAMEBUFFER = Path('/dev/fb0')
FRAMEBUFFER_INFO = Path('/sys/class/graphics/fb0')
INPUT_DEVICES = Path('/proc/bus/input/devices')
# The touch screens Juggle OS knows: the official Touch Display's controller
TOUCH_NAMES = ('ft5x06', 'edt-ft5x06', 'Touchscreen')
FBIOGET_VSCREENINFO = 0x4600
# For quarter turns clockwise of the picture: how a part of the panel's picture is turned for the framebuffer
TURNS = (None, Image.Transpose.ROTATE_270, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_90)

# RGB565, made with Pillow's channel operations (Pillow 11 has no packer for it): each pixel's low byte is green's
# low three bits and blue's top five, its high byte red's top five and green's top three
_LOW_G = [(v << 3) & 0xE0 for v in range(256)]
_LOW_B = [v >> 3 for v in range(256)]
_HIGH_R = [v & 0xF8 for v in range(256)]
_HIGH_G = [v >> 5 for v in range(256)]


def rgb565(image):
    """An RGB image's pixels as the framebuffer's 16-bit RGB565, little-endian."""
    r, g, b = image.convert('RGB').split()
    low = ImageChops.add(g.point(_LOW_G), b.point(_LOW_B))
    high = ImageChops.add(r.point(_HIGH_R), g.point(_HIGH_G))
    return Image.merge('LA', (low, high)).tobytes()


def screen_corner(box, rotation, screen_width, screen_height):
    """Where a box of the panel's picture (left, top, right, bottom) starts in the framebuffer, once turned."""
    left, top, right, bottom = box
    return [(left, top), (screen_width - bottom, left), (screen_width - right, screen_height - bottom),
            (top, screen_height - right)][rotation]


class Framebuffer:
    """The screen on the Pi. memory is the framebuffer (mmap, or a bytearray in tests); the screen is width x height
    pixels in it (the framebuffer can be larger), stride bytes a line."""

    def __init__(self, memory, width, height, stride, bits_per_pixel, rotation):
        self.memory, self.stride, self.bytes_per_pixel = memory, stride, bits_per_pixel // 8
        self.screen_size = (width, height)
        self.rotation = rotation // 90 % 4
        self.size = (width, height) if self.rotation % 2 == 0 else (height, width)

    @classmethod
    def open(cls, rotation):
        import fcntl  # Linux only (the Pi)
        with open(FRAMEBUFFER, 'rb') as framebuffer:
            width, height = struct.unpack('2I', fcntl.ioctl(framebuffer, FBIOGET_VSCREENINFO, bytes(160))[:8])
        stride = int((FRAMEBUFFER_INFO / 'stride').read_text())
        bits_per_pixel = int((FRAMEBUFFER_INFO / 'bits_per_pixel').read_text())
        fd = os.open(FRAMEBUFFER, os.O_RDWR)
        try:
            memory = mmap.mmap(fd, stride * height)
        finally:
            os.close(fd)
        return cls(memory, width, height, stride, bits_per_pixel, rotation)

    def show(self, image, box=None):
        """Puts the part of image in box (all of it without one) on the screen."""
        box = box or (0, 0, *image.size)
        part = image.crop(box)
        if TURNS[self.rotation] is not None:
            part = part.transpose(TURNS[self.rotation])
        left, top = screen_corner(box, self.rotation, *self.screen_size)
        raw = rgb565(part) if self.bytes_per_pixel == 2 else part.convert('RGB').tobytes('raw', 'BGRX')
        line = part.width * self.bytes_per_pixel
        for row in range(part.height):
            start = (top + row) * self.stride + left * self.bytes_per_pixel
            self.memory[start:start + line] = raw[row * line:(row + 1) * line]


# An input event (struct input_event): seconds, microseconds, type, code, value
EVENT = struct.Struct('llHHi')
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y, BTN_TOUCH = 0, 1, 330


class Touches:
    """Turns the touch screen's input events into touches: ('down' | 'move' | 'up', x, y), one finger."""

    def __init__(self, size):
        self.size = size
        self.x = self.y = 0
        self.touching = self.reported = False
        self.pending = b''

    def feed(self, data):
        """The touches in data (input events, which may end part way through one)."""
        data = self.pending + data
        whole = len(data) - len(data) % EVENT.size
        self.pending = data[whole:]
        touches = []
        moved = False
        for offset in range(0, whole, EVENT.size):
            _, _, kind, code, value = EVENT.unpack_from(data, offset)
            if kind == EV_ABS and code in (ABS_X, ABS_Y):
                if code == ABS_X:
                    self.x = min(max(value, 0), self.size[0] - 1)
                else:
                    self.y = min(max(value, 0), self.size[1] - 1)
                moved = True
            elif kind == EV_KEY and code == BTN_TOUCH:
                self.touching = value != 0
            elif kind == EV_SYN and code == 0:
                if self.touching and not self.reported:
                    touches.append(('down', self.x, self.y))
                elif self.touching and moved:
                    touches.append(('move', self.x, self.y))
                elif not self.touching and self.reported:
                    touches.append(('up', self.x, self.y))
                self.reported, moved = self.touching, False
        return touches


def touch_device():
    """The touch screen's input device (/dev/input/eventN), or None."""
    try:
        blocks = INPUT_DEVICES.read_text().split('\n\n')
    except OSError:
        return None
    for block in blocks:
        name = next((line for line in block.splitlines() if line.startswith('N: Name=')), '')
        if any(known in name for known in TOUCH_NAMES):
            for line in block.splitlines():
                if line.startswith('H: Handlers='):
                    handler = next((h for h in line.split('=', 1)[1].split() if h.startswith('event')), None)
                    if handler:
                        return '/dev/input/' + handler
    return None


class PiScreen:
    """The Touch Display on a Pi running Juggle OS."""

    def __init__(self, rotation):
        self.framebuffer = Framebuffer.open(rotation)
        self.size = self.framebuffer.size
        self.show = self.framebuffer.show

    async def run(self, touched):
        """Calls touched(kind, x, y) for each touch, for as long as the app runs."""
        device = touch_device()
        if device is None:
            await asyncio.Event().wait()  # a screen without touch: only pictures
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
        touches = Touches(self.size)
        ready = asyncio.Event()
        asyncio.get_running_loop().add_reader(fd, ready.set)
        while True:
            await ready.wait()
            ready.clear()
            try:
                data = os.read(fd, EVENT.size * 64)
            except BlockingIOError:
                continue
            for touch in touches.feed(data):
                touched(*touch)


class Window:
    """A window standing in for the screen on a PC, with the mouse as the finger."""

    def __init__(self, size):
        import tkinter
        from PIL import ImageTk
        self.size = size
        self.root = tkinter.Tk()
        self.root.title('HA Control Panel')
        self.root.resizable(False, False)
        self.photo = ImageTk.PhotoImage(Image.new('RGB', size))
        tkinter.Label(self.root, image=self.photo, borderwidth=0).pack()
        self.picture = Image.new('RGB', size)

    def show(self, image, box=None):
        box = box or (0, 0, *image.size)
        self.picture.paste(image.crop(box), box[:2])
        self.photo.paste(self.picture)

    async def run(self, touched):
        def mouse(kind):
            return lambda event: touched(kind, min(max(event.x, 0), self.size[0] - 1),
                                         min(max(event.y, 0), self.size[1] - 1))
        self.root.bind('<ButtonPress-1>', mouse('down'))
        self.root.bind('<B1-Motion>', mouse('move'))
        self.root.bind('<ButtonRelease-1>', mouse('up'))
        while True:
            self.root.update()
            await asyncio.sleep(0.02)


def open_screen(rotation, pc_size):
    """The Pi's screen when there is one, otherwise a window of pc_size (a PC)."""
    if FRAMEBUFFER.exists():
        return PiScreen(rotation)
    return Window(pc_size)
