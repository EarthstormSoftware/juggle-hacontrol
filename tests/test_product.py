"""The panel's own part, on App Base's real device and settings (saved in a temporary folder)."""
import json
import re
import types

import pytest

import icons
import kinds
import panel
import product
from base.device import Device


@pytest.fixture
def device(tmp_path):
    platform = types.SimpleNamespace(state_path=lambda name: str(tmp_path / name), device_name=lambda: 'panel',
                                     NAME_EDITABLE=False, health=lambda: {}, SENSORS=())
    return Device(product, platform)


def test_without_settings_home_assistant_isnt_set_up(device):
    assert product.info(device)['home_assistant'] == {'status': 'not set up', 'connected': False, 'version': None}
    assert product.state(device) == {'home_assistant': 'not set up'}


def test_the_token_is_kept_but_only_shown_as_set(device, tmp_path):
    assert device.change({'ha': {'address': '192.168.1.10', 'token': 'secret-token'}}) is None
    view = device.settings.view()['ha']
    assert view == {'address': '192.168.1.10', 'token_set': True}
    assert json.loads((tmp_path / 'config.json').read_text())['ha']['token'] == 'secret-token'


def test_new_settings_go_to_the_connection_at_once(device):
    ha = product.connection(device)
    device.change({'ha': {'address': 'homeassistant.local:8124', 'token': 'abc'}})
    assert (ha.address, ha.token) == ('homeassistant.local:8124', 'abc')
    device.change({'ha': {'token': None}})  # removed on the page
    assert ha.token == ''


@pytest.mark.parametrize('address', ['', '192.168.1.10', 'homeassistant.local:8123', 'http://192.168.1.10:8123',
                                     'ws://ha.example/'])
def test_addresses_home_assistant_can_have(device, address):
    assert device.change({'ha': {'address': address}}) is None


@pytest.mark.parametrize('address', ['https://192.168.1.10', 'ha local', '192.168.1.10:99999', 'http://', 5])
def test_addresses_it_cant_have_are_refused(device, address):
    assert device.change({'ha': {'address': address}}) is not None
    assert device.settings.get('ha', 'address') == ''


def test_the_pages_are_kept_and_every_pages_entities_watched_once(device):
    pages = [{'name': 'Kitchen', 'tiles': [{'entity_id': 'light.kitchen', 'name': 'Worktop', 'size': '2x1'},
                                           {'entity_id': 'sensor.hall'}]},
             {'name': 'Hall', 'tiles': [{'entity_id': 'sensor.hall'}, {'entity_id': 'switch.fan'}]}]
    assert device.change({'screen': {'pages': pages}}) is None
    assert product.connection(device).watched == ['light.kitchen', 'sensor.hall', 'switch.fan']
    chosen = product.chosen_pages(device)
    assert [page.name for page in chosen] == ['Kitchen', 'Hall']
    assert [(t.entity_id, t.name, t.size) for t in chosen[0].tiles] == [('light.kitchen', 'Worktop', '2x1'),
                                                                        ('sensor.hall', None, 'auto')]


def page(tiles, name='Page'):
    return [{'name': name, 'tiles': tiles}]


@pytest.mark.parametrize('pages', [
    'light.kitchen', page('light.kitchen'), page([{'entity_id': 'automation.night'}]),
    page([{'entity_id': 'light.kitchen'}] * 2), page([{'entity_id': 'light.Kitchen'}]),
    page([{'entity_id': 'light.kitchen', 'name': 'x' * 33}]), page([{'entity_id': 'light.kitchen', 'colour': 'red'}]),
    page([{'entity_id': 'sensor.s{}'.format(n)} for n in range(13)]), page([], name='x' * 21),
    page([{'entity_id': 'light.kitchen', 'size': '5x1'}]), page([{'entity_id': 'light.kitchen', 'icon': 'cat'}]),
    page([{'entity_id': 'sensor.hall', 'show': 'pie'}]), page([{'entity_id': 'sensor.hall', 'hours': 5}]),
    page([{'entity_id': 'sensor.hall', 'hours': True}]), page([{'entity_id': 'sensor.hall', 'gauge': [30, 10]}]),
    page([{'entity_id': 'sensor.hall', 'gauge': [0]}]), page([{'entity_id': 'sensor.hall', 'gauge': ['0', 9]}]),
    [{'tiles': []}], page([]) * 7])
def test_pages_that_cant_be_are_refused(device, pages):
    assert device.change({'screen': {'pages': pages}}) is not None
    assert device.settings.get('screen', 'pages') == []


def test_a_tiles_icon_way_of_showing_history_and_gauge_are_kept(device):
    tile = {'entity_id': 'sensor.hall', 'icon': 'auto', 'show': 'gauge', 'hours': 6, 'gauge': [10, 25.5]}
    assert device.change({'screen': {'pages': page([tile, {'entity_id': 'binary_sensor.door', 'show': 'graph'}])}})         is None
    hall, door = product.chosen_pages(device)[0].tiles
    assert (hall.icon, hall.show, hall.hours, hall.gauge) == ('auto', 'gauge', 6, (10, 25.5))
    assert (door.icon, door.show, door.hours, door.gauge) == ('none', 'graph', 24, None)


@pytest.mark.parametrize('sizes, refused', [
    ({'name_size': 'small', 'value_size': 'xlarge'}, False), ({'value_size': 'large'}, False),
    ({'name_size': 'xlarge'}, True), ({'value_size': 'tiny'}, True), ({'text': 'tiny'}, True)])
def test_a_pages_names_and_content_are_fitted_or_one_size(device, sizes, refused):
    pages = [dict({'name': 'Hall', 'tiles': []}, **sizes), {'name': 'Kitchen', 'tiles': []}]
    assert (device.change({'screen': {'pages': pages}}) is not None) == refused
    if not refused:
        hall, kitchen = product.chosen_pages(device)
        assert (hall.name_size, hall.value_size) == (sizes.get('name_size', 'fit'), sizes.get('value_size', 'fit'))
        assert (kitchen.name_size, kitchen.value_size) == ('fit', 'fit')


def test_a_page_saved_with_one_text_size_has_it_for_names_and_content(device):
    assert device.change({'screen': {'pages': [{'name': 'Hall', 'tiles': [], 'text': 'medium'}]}}) is None
    hall, = product.chosen_pages(device)
    assert (hall.name_size, hall.value_size) == ('medium', 'medium')


@pytest.mark.parametrize('values', [{'timeout_minutes': -1}, {'timeout_minutes': 241}, {'brightness': 4},
                                    {'brightness': 101}])
def test_the_screens_timeout_and_brightness_have_limits(device, values):
    assert device.change({'screen': values}) is not None


def test_the_version_is_the_manifests():
    manifest = json.loads((product.Path(product.__file__).parent / 'app.json').read_text())
    assert product.VERSION == manifest['version']
    assert manifest['juggle'] == '1.1' and manifest['name'] == 'hacontrol' and manifest['display'] is True


def test_the_pages_icons_are_the_ones_the_screen_draws():
    page = (product.Path(product.__file__).parent / 'www' / 'index.html').read_text(encoding='utf-8')
    listed = re.search(r'var ICONS = \[(.*?)\];', page, re.S).group(1)
    assert tuple(re.findall(r"\['(\w+)', '", listed)) == kinds.ICONS == tuple(icons.DRAWN)


@pytest.mark.parametrize('layout, bad', [('rooms', False), ('tiles', False), ('columns', True)])
def test_a_page_may_be_laid_out_in_rooms(layout, bad):
    page = {'name': 'Lights', 'layout': layout, 'tiles': [{'entity_id': 'light.a', 'group': 'Kitchen'}]}
    assert bool(product.check_pages([page])) is bad


def test_a_room_name_can_only_be_so_long():
    assert product.check_pages([{'name': 'L', 'tiles': [{'entity_id': 'light.a', 'group': 'x' * 21}]}])


@pytest.mark.parametrize('entity_id', ['cover.blind', 'weather.home'])
def test_blinds_and_the_weather_can_be_tiles(entity_id):
    assert product.check_pages([{'name': 'H', 'tiles': [{'entity_id': entity_id}]}]) is None


def test_the_weather_may_be_on_a_page_as_it_is_now_and_tomorrow_but_nothing_else_twice():
    weather = [{'entity_id': 'weather.home', 'show': 'today'}, {'entity_id': 'weather.home', 'show': 'tomorrow'}]
    assert product.check_tiles(weather) is None
    assert product.check_tiles(weather + [{'entity_id': 'weather.home', 'show': 'tomorrow'}])
    assert product.check_tiles([{'entity_id': 'light.a'}, {'entity_id': 'light.a'}])


def test_only_tiles_showing_tomorrow_ask_for_a_forecast():
    pages = [panel.Page('H', [panel.Tile('weather.home', show='today'), panel.Tile('weather.home', show='tomorrow'),
                              panel.Tile('weather.other'), panel.Tile('sensor.a')])]
    assert product.forecast_entities(pages) == ['weather.home']
