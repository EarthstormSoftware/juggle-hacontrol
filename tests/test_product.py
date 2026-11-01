"""The panel's own part, on App Base's real device and settings (saved in a temporary folder)."""
import json
import types

import pytest

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


def test_the_tiles_are_kept_and_watched_in_home_assistant(device):
    tiles = [{'entity_id': 'light.kitchen', 'name': 'Worktop'}, {'entity_id': 'sensor.hall'}]
    assert device.change({'screen': {'tiles': tiles}}) is None
    assert product.connection(device).watched == ['light.kitchen', 'sensor.hall']
    assert [(t.entity_id, t.name) for t in product.chosen_tiles(device)] == [('light.kitchen', 'Worktop'),
                                                                         ('sensor.hall', None)]


@pytest.mark.parametrize('tiles', [
    'light.kitchen', [{'entity_id': 'automation.night'}], [{'entity_id': 'light.kitchen'}] * 2,
    [{'entity_id': 'light.Kitchen'}], [{'entity_id': 'light.kitchen', 'name': 'x' * 33}],
    [{'entity_id': 'light.kitchen', 'colour': 'red'}], [{'entity_id': 'sensor.s{}'.format(n)} for n in range(9)]])
def test_tiles_that_cant_be_are_refused(device, tiles):
    assert device.change({'screen': {'tiles': tiles}}) is not None
    assert device.settings.get('screen', 'tiles') == []


def test_the_version_is_the_manifests():
    manifest = json.loads((product.Path(product.__file__).parent / 'app.json').read_text())
    assert product.VERSION == manifest['version']
    assert manifest['juggle'] == '1.1' and manifest['name'] == 'hacontrol' and manifest['display'] is True
