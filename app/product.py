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
import time
from pathlib import Path

from base.log import Log
from base.settings import Setting, is_int, is_text
from ha import HomeAssistant, check_address
from panel import (DOMAINS, HOURS, ICON_CHOICES, LAYOUTS, MOST_PAGES, MOST_TILES, NAME_TEXTS, SHOWS, SIZES, VALUE_TEXTS,
                   Page, Tile)

NAME = 'HA Control Panel'
VERSION = json.loads((Path(__file__).parent / 'app.json').read_text(encoding='utf-8'))['version']
TAG = 'PANEL'
ENTITY_ID = re.compile(r'([a-z_]+)\.[a-z0-9_]+')
LONGEST_NAME = 32
LONGEST_PAGE_NAME = 20
LONGEST_ROOM = 20
TILE_KEYS = {'entity_id', 'name', 'size', 'icon', 'show', 'hours', 'gauge', 'group'}
# A page's: text was its names' and content's size together (2026-11-03, briefly), kept so a page saved with it loads
PAGE_KEYS = {'name', 'tiles', 'name_size', 'value_size', 'text', 'layout'}
OLD_TEXTS = ('fit', 'large', 'medium', 'small')
# How long the screen says an action failed
FAILED_SECONDS = 5
# How often a forecast is asked for, and how often whether it's time to
FORECAST_EVERY = 30 * 60
FORECAST_CHECK = 60


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < 1e9


def check_tiles(value):
    """A Setting check for the tiles: [{"entity_id", "name", "size", "icon", "show", "hours", "gauge"}], all but
    entity_id optional: name (Home Assistant's otherwise), size one of SIZES ('auto'), icon one of ICON_CHOICES
    ('none'), show one of SHOWS ('value'), hours one of HOURS (24), gauge [low, high] (the one that suits its kind),
    group the room it's in on a page laid out in rooms."""
    if not isinstance(value, list) or len(value) > MOST_TILES:
        return 'must be a list of up to {} tiles'.format(MOST_TILES)
    seen = set()
    for tile in value:
        if not isinstance(tile, dict) or set(tile) - TILE_KEYS:
            return 'must be tiles of {}'.format(', '.join(sorted(TILE_KEYS)))
        entity_id, name = tile.get('entity_id'), tile.get('name', '')
        found = ENTITY_ID.fullmatch(entity_id) if isinstance(entity_id, str) else None
        if not found or found.group(1) not in DOMAINS:
            return 'has {!r}, which isn\'t a light, switch, blind, sensor, binary sensor or weather'.format(entity_id)
        # (the weather may be on a page twice, as it is now and tomorrow)
        key = entity_id, tile.get('show', 'value') if found.group(1) == 'weather' else None
        if key in seen:
            return 'has {} twice'.format(entity_id)
        seen.add(key)
        if not isinstance(name, str) or len(name) > LONGEST_NAME:
            return 'has a name longer than {} characters'.format(LONGEST_NAME)
        group = tile.get('group', '')
        if not isinstance(group, str) or len(group) > LONGEST_ROOM:
            return 'has a room name longer than {} characters'.format(LONGEST_ROOM)
        if tile.get('size', 'auto') not in SIZES:
            return 'has a size that isn\'t one of {}'.format(', '.join(SIZES))
        if tile.get('icon', 'none') not in ICON_CHOICES:
            return 'has an icon that isn\'t one of {}'.format(', '.join(ICON_CHOICES))
        if tile.get('show', 'value') not in SHOWS:
            return 'has a way to show it that isn\'t one of {}'.format(', '.join(SHOWS))
        hours = tile.get('hours', 24)
        if isinstance(hours, bool) or hours not in HOURS:
            return 'has hours of history that aren\'t one of {}'.format(', '.join(str(n) for n in HOURS))
        gauge = tile.get('gauge')
        if gauge is not None and not (isinstance(gauge, list) and len(gauge) == 2 and all(map(is_number, gauge))
                                      and gauge[0] < gauge[1]):
            return 'has a gauge that isn\'t [low, high]'
    return None


def check_pages(value):
    """A Setting check for the pages: [{"name", "tiles", "name_size", "value_size"}], each page's tiles as check_tiles
    has them, and (optional, 'fit' otherwise) the size of its tiles' names, one of NAME_TEXTS, and of their content,
    one of VALUE_TEXTS."""
    if not isinstance(value, list) or len(value) > MOST_PAGES:
        return 'must be a list of up to {} pages'.format(MOST_PAGES)
    for page in value:
        if not isinstance(page, dict) or not {'name', 'tiles'} <= set(page) <= PAGE_KEYS:
            return 'must be pages of name, tiles, name_size and value_size'
        if page.get('layout', 'tiles') not in LAYOUTS:
            return "has a layout that isn't one of {}".format(', '.join(LAYOUTS))
        if page.get('name_size', 'fit') not in NAME_TEXTS:
            return "has a name size that isn't one of {}".format(', '.join(NAME_TEXTS))
        if page.get('value_size', 'fit') not in VALUE_TEXTS:
            return "has a content size that isn't one of {}".format(', '.join(VALUE_TEXTS))
        if page.get('text', 'fit') not in OLD_TEXTS:
            return "has a text size that isn't one of {}".format(', '.join(OLD_TEXTS))
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
        # Dark after so many minutes without a touch (0: never): this panel's default is 5, the base's 0. How bright it
        # is when it's on is the base's (brightness).
        'timeout_minutes': Setting(5, is_int(0, 240)),
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
    return [Page(page['name'], [Tile(tile['entity_id'], tile.get('name') or None, tile.get('size', 'auto'),
                                     tile.get('icon', 'none'), tile.get('show', 'value'), tile.get('hours', 24),
                                     tile.get('gauge'), tile.get('group') or None)
                                for tile in page['tiles']],
                 page.get('name_size', page.get('text', 'fit')), page.get('value_size', page.get('text', 'fit')),
                 page.get('layout', 'tiles'))
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
        panel.power.apply(device.settings)
        panel.set_pages(pages, hint=None if any(page.tiles for page in pages) else 'Choose tiles on http://{}.local'
                        .format(device.platform.device_name()))


def info(device):
    ha = connection(device)
    panel = getattr(device, 'panel', None)
    # The screen's grid, for the page to say how many cells a page's tiles take
    return {'home_assistant': {'status': ha.status, 'connected': ha.connected, 'version': ha.version},
            'screen': {'columns': panel.grid[0], 'rows': panel.grid[1]} if panel else None}


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
    return [connection(device).run(), screen_task(device), forecast_task(device)]


def forecast_entities(pages):
    """The weather entities whose tiles show tomorrow's forecast, each once."""
    return list(dict.fromkeys(tile.entity_id for page in pages for tile in page.tiles
                              if tile.domain == 'weather' and tile.show == 'tomorrow'))


async def forecast_task(device):
    """Keeps the forecasts up to date: Home Assistant doesn't send them as it does a state, so they're asked for, every
    so often and at once when a tile starts to want one."""
    ha = connection(device)
    asked, again = None, 0
    while True:
        wanted = forecast_entities(chosen_pages(device))
        if ha.connected and wanted and (wanted != asked or time.monotonic() >= again):
            try:
                for entity_id in wanted:
                    ha.forecasts[entity_id] = await ha.daily_forecast(entity_id)
                asked, again = wanted, time.monotonic() + FORECAST_EVERY
                panel = getattr(device, 'panel', None)
                if panel:
                    panel.changed(set(wanted))
            except Exception as e:  # not connected, timed out, or refused: asked again before long
                Log.warn(TAG, "Couldn't get the forecast: {}".format(e))
        await asyncio.sleep(FORECAST_CHECK)


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

    def adjust(tile, data):
        """A light's brightness, warmth, colour or effect (light.turn_on's data); a brightness of 0 turns it off."""
        if data.get('brightness_pct') == 0:
            act('switch off ' + tile.look(panel.state(tile.entity_id))[0],
                ha.call_service('light', 'turn_off', tile.entity_id))
        else:
            what = {'brightness_pct': 'brightness', 'color_temp_kelvin': 'warmth', 'hs_color': 'colour',
                    'effect': 'effect'}.get(next(iter(data), ''), 'light')
            act('set the ' + what, ha.call_service('light', 'turn_on', tile.entity_id, **data))

    async def history(entity_id, hours):
        try:
            return await ha.history(entity_id, hours)
        except Exception as e:
            Log.warn(TAG, "Couldn't get {}'s history: {}".format(entity_id, e))
            raise

    def state(entity_id):
        """An entity's state, with its forecast if it has one."""
        found = ha.states.get(entity_id) if ha.connected else None
        forecast = ha.forecasts.get(entity_id)
        return dict(found, forecast=forecast) if found and forecast else found

    panel = Panel(screen, state=state, tapped=tapped, adjust=adjust, history=history)
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
