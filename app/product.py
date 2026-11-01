"""Juggle HA Control Panel: a Juggle OS app showing Home Assistant's lights and sensors on the Pi's touch screen
(docs/roadmap.md).

App Base (base/) does the page's Device and MQTT tabs, the settings, the API and MQTT, and asks Juggle OS for what the
OS owns (the Pi's name, Wi-Fi, setup mode, the clock, the display's rotation). This is the panel's own: the Home
Assistant connection (ha.py, its address and token set on the page), and the screen (screen.py, panel.py).
"""
import asyncio
import json
import os
import re
from pathlib import Path

from base.log import Log
from base.settings import Setting, is_int, is_text
from ha import HomeAssistant, check_address
from panel import DOMAINS, MOST_PAGES, MOST_TILES, Page, Tile

NAME = 'HA Control Panel'
VERSION = json.loads((Path(__file__).parent / 'app.json').read_text(encoding='utf-8'))['version']
TAG = 'PANEL'
ENTITY_ID = re.compile(r'([a-z_]+)\.[a-z0-9_]+')
LONGEST_NAME = 32
LONGEST_PAGE_NAME = 20
# How long the screen says an action failed
FAILED_SECONDS = 5


def check_tiles(value):
    """A Setting check for the tiles: [{"entity_id", "name"}], name optional (Home Assistant's otherwise)."""
    if not isinstance(value, list) or len(value) > MOST_TILES:
        return 'must be a list of up to {} tiles'.format(MOST_TILES)
    seen = set()
    for tile in value:
        if not isinstance(tile, dict) or set(tile) - {'entity_id', 'name'}:
            return 'must be tiles of entity_id and name'
        entity_id, name = tile.get('entity_id'), tile.get('name', '')
        found = ENTITY_ID.fullmatch(entity_id) if isinstance(entity_id, str) else None
        if not found or found.group(1) not in DOMAINS:
            return 'has {!r}, which isn\'t a light, switch, sensor or binary sensor'.format(entity_id)
        if entity_id in seen:
            return 'has {} twice'.format(entity_id)
        seen.add(entity_id)
        if not isinstance(name, str) or len(name) > LONGEST_NAME:
            return 'has a name longer than {} characters'.format(LONGEST_NAME)
    return None


def check_pages(value):
    """A Setting check for the pages: [{"name", "tiles"}], each page's tiles as check_tiles has them."""
    if not isinstance(value, list) or len(value) > MOST_PAGES:
        return 'must be a list of up to {} pages'.format(MOST_PAGES)
    for page in value:
        if not isinstance(page, dict) or set(page) != {'name', 'tiles'}:
            return 'must be pages of name and tiles'
        if not isinstance(page['name'], str) or len(page['name']) > LONGEST_PAGE_NAME:
            return 'has a page name longer than {} characters'.format(LONGEST_PAGE_NAME)
        error = check_tiles(page['tiles'])
        if error:
            return error
    return None


SETTINGS = {
    'ha': {
        # Home Assistant's address, such as 192.168.1.10 (port 8123 unless given)
        'address': Setting('', check_address),
        # A long-lived access token (the user's profile in Home Assistant, Security): kept on the Pi, never shown
        'token': Setting('', is_text(1024, allow_empty=False), secret=True),
    },
    'screen': {
        # What the screen shows: pages of tiles, in order
        'pages': Setting([], check_pages),
        # Dark after so many minutes without a touch (0: never), and how bright when it's on
        'timeout_minutes': Setting(5, is_int(0, 240)),
        'brightness': Setting(100, is_int(5, 100)),
    },
}


def connection(device):
    """The device's Home Assistant connection, made the first time it's asked for."""
    if not hasattr(device, 'home_assistant'):
        device.home_assistant = HomeAssistant()
        device.home_assistant.watch(watched(chosen_pages(device)))
        configure(device)
    return device.home_assistant


def configure(device):
    connection(device).configure(device.settings.get('ha', 'address'), device.settings.reveal('ha', 'token'))


def chosen_pages(device):
    return [Page(page['name'], [Tile(tile['entity_id'], tile.get('name') or None) for tile in page['tiles']])
            for page in device.settings.get('screen', 'pages')]


def watched(pages):
    """Every page's entities, each once: all of them are kept up to date, so changing the page is at once."""
    return list(dict.fromkeys(tile.entity_id for page in pages for tile in page.tiles))


def show_pages(device):
    """The pages as set: watched in Home Assistant, and on the screen, with its timeout and brightness."""
    pages = chosen_pages(device)
    connection(device).watch(watched(pages))
    panel = getattr(device, 'panel', None)
    if panel:
        panel.timeout = device.settings.get('screen', 'timeout_minutes') * 60
        backlight = getattr(panel.screen, 'backlight', None)
        if backlight:
            backlight.set_brightness(device.settings.get('screen', 'brightness'))
        panel.set_pages(pages, hint=None if any(page.tiles for page in pages) else 'Choose tiles on http://{}.local'
                        .format(device.platform.device_name()))


def info(device):
    ha = connection(device)
    return {'home_assistant': {'status': ha.status, 'connected': ha.connected, 'version': ha.version}}


def state(device):
    """The state topic (<topic base>/state)."""
    return {'home_assistant': connection(device).status}


def applied(device, changed):
    if any(section == 'ha' for section, _ in changed):
        configure(device)
    if any(section == 'screen' for section, _ in changed):
        show_pages(device)


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
    from panel import Panel
    from screen import open_screen
    ha = connection(device)
    screen = open_screen(rotation(device), pc_size())

    def status():
        # The screen says only what's wrong; the page says why
        return None if ha.connected else 'Home Assistant: ' + ha.status.split(':', 1)[0]

    def act(what, call):
        async def go():
            try:
                await call
            except Exception as e:  # not connected, timed out, or refused
                Log.warn(TAG, "Couldn't {}: {}".format(what, e))
                panel.set_status("Couldn't {}".format(what))
                await asyncio.sleep(FAILED_SECONDS)
                panel.set_status(status())
        asyncio.ensure_future(go())

    def tapped(tile):
        act('switch ' + tile.look(panel.state(tile.entity_id))[0], ha.call_service(tile.domain, 'toggle',
                                                                                   tile.entity_id))

    def brightness(tile, percent):
        call = ha.call_service('light', 'turn_on', tile.entity_id, brightness_pct=percent) if percent \
            else ha.call_service('light', 'turn_off', tile.entity_id)
        act('set the brightness', call)

    panel = Panel(screen, state=lambda entity_id: ha.states.get(entity_id) if ha.connected else None,
                  tapped=tapped, brightness=brightness)
    device.panel = panel
    show_pages(device)

    def changed(entity_ids):
        panel.set_status(status())
        panel.changed(entity_ids)
    ha.changed = changed
    panel.set_status(status())
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
