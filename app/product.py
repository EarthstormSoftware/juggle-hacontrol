"""Juggle HA Control Panel: a Juggle OS app showing Home Assistant's lights and sensors on the Pi's touch screen
(docs/roadmap.md).

App Base (base/) does the page's Device and MQTT tabs, the settings, the API and MQTT, and asks Juggle OS for what the
OS owns (the Pi's name, Wi-Fi, setup mode, the clock, the display's rotation). This is the panel's own: the Home
Assistant connection (ha.py, its address and token set on the page), and the screen (screen.py, panel.py).
"""
import asyncio
import json
import os
from pathlib import Path

from base.settings import Setting, is_text
from ha import HomeAssistant, check_address

NAME = 'HA Control Panel'
VERSION = json.loads((Path(__file__).parent / 'app.json').read_text(encoding='utf-8'))['version']

SETTINGS = {
    'ha': {
        # Home Assistant's address, such as 192.168.1.10 (port 8123 unless given)
        'address': Setting('', check_address),
        # A long-lived access token (the user's profile in Home Assistant, Security): kept on the Pi, never shown
        'token': Setting('', is_text(1024, allow_empty=False), secret=True),
    },
}


def connection(device):
    """The device's Home Assistant connection, made the first time it's asked for."""
    if not hasattr(device, 'home_assistant'):
        device.home_assistant = HomeAssistant()
        configure(device)
    return device.home_assistant


def configure(device):
    connection(device).configure(device.settings.get('ha', 'address'), device.settings.reveal('ha', 'token'))


def info(device):
    ha = connection(device)
    return {'home_assistant': {'status': ha.status, 'connected': ha.connected, 'version': ha.version}}


def state(device):
    """The state topic (<topic base>/state)."""
    return {'home_assistant': connection(device).status}


def applied(device, changed):
    if any(section == 'ha' for section, _ in changed):
        configure(device)


def routes(app, device):
    @app.get('/api/ha/entities')
    async def entities(request):
        """Home Assistant's lights, sensors and switches, for choosing tiles."""
        try:
            return {'entities': await connection(device).entities()}
        except Exception as e:  # not connected, timed out, or refused: the page says why
            return {'success': False, 'error': str(e) or type(e).__name__}, 400


def tasks(device):
    return [connection(device).run(), screen_task(device)]


async def screen_task(device):
    """The panel on the screen (screen.py, panel.py), for as long as the app runs."""
    from panel import Panel, Tile
    from screen import open_screen
    screen = open_screen(rotation(device), pc_size())
    panel = Panel(screen, [Tile('Test')])
    ha = connection(device)
    # The screen says only what's wrong; the page says why
    ha.changed = lambda entity_ids: panel.set_status(
        None if ha.connected else 'Home Assistant: ' + ha.status.split(':', 1)[0])
    ha.changed(None)
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
