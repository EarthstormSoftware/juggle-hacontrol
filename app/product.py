"""Juggle HA Control Panel: a Juggle OS app showing Home Assistant's lights and sensors on the Pi's touch screen
(docs/roadmap.md). For now it's still Juggle Hello's greeting, which the screen replaces.

App Base (base/) does the page's Device and MQTT tabs, the settings, the API, MQTT and Home Assistant discovery, and
asks Juggle OS for what the OS owns (the Pi's name, Wi-Fi, setup mode, the clock, the display's rotation).
"""
import asyncio
import json
import os
from pathlib import Path

from base.settings import Setting, is_text

NAME = 'HA Control Panel'
VERSION = json.loads((Path(__file__).parent / 'app.json').read_text(encoding='utf-8'))['version']

GREETING_LONGEST = 64

SETTINGS = {
    'hello': {
        'greeting': Setting('Hello from Juggle OS', is_text(GREETING_LONGEST, allow_empty=False)),
    },
}

# Home Assistant: the greeting, as a text box
HA_ENTITIES = (('text', 'greeting'),)


def info(device):
    return {'greeting': device.settings.get('hello', 'greeting')}


def state(device):
    """The state topic (<topic base>/state)."""
    return {'greeting': device.settings.get('hello', 'greeting')}


def set(device, command):
    """A command on the set topic (<topic base>/set): {"greeting": "..."}."""
    if any(key != 'greeting' for key in command):
        return 'only greeting can be set'
    return device.change({'hello': command})


def applied(device, changed):
    # A new greeting from the page, the API or MQTT: the state topic says so
    if any(section == 'hello' for section, _ in changed):
        device.state_changed()


def tasks(device):
    return [screen_task(device)]


async def screen_task(device):
    """The panel on the screen (screen.py, panel.py), for as long as the app runs."""
    from panel import Panel, Tile
    from screen import open_screen
    screen = open_screen(rotation(device), pc_size())
    panel = Panel(screen, [Tile('Test')])
    await asyncio.gather(panel.run(), screen.run(panel.touched))


def rotation(device):
    """How far the display's picture is turned (Juggle OS's display-rotation), or 0 where the OS doesn't say."""
    platform = device.platform
    if getattr(platform, 'os_display', lambda: False)():
        try:
            return platform.display()['rotation']
        except platform.RequestError:
            pass
    return 0


def pc_size():
    """The window's size on a PC: SCREEN=480x800 for portrait, 800x480 (landscape) otherwise."""
    width, _, height = os.environ.get('SCREEN', '800x480').partition('x')
    return (int(width), int(height)) if width.isdigit() and height.isdigit() else (800, 480)


def ha_entity(device, key, t):
    return {'name': 'Greeting', 'icon': 'mdi:hand-wave', 'max': GREETING_LONGEST,
            'value_template': '{{ value_json.greeting }}',
            'command_topic': t['set'], 'command_template': '{"greeting": {{ value | tojson }}}'}
