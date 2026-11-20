"""Draws the sample screenshots in this folder: the panel's own drawing code, fed made-up Home Assistant states, so
no real home, address or token is involved. Run from the repo's root: py docs/sample/render_sample.py"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'app'))

import panel  # noqa: E402

STATES = {
    'light.living_room': {'state': 'on', 'attributes': {'friendly_name': 'Living Room', 'brightness': 180,
                                                         'supported_color_modes': ['brightness']}},
    'light.kitchen': {'state': 'on', 'attributes': {'friendly_name': 'Kitchen', 'brightness': 255,
                                                     'supported_color_modes': ['brightness']}},
    'light.hallway': {'state': 'off', 'attributes': {'friendly_name': 'Hallway', 'supported_color_modes': ['onoff']}},
    'light.bedroom': {'state': 'off', 'attributes': {'friendly_name': 'Bedroom', 'supported_color_modes': ['onoff']}},
    'light.desk_strip': {'state': 'on', 'attributes': {'friendly_name': 'Desk Strip', 'brightness': 120,
                                                        'supported_color_modes': ['color_temp', 'hs']}},
    'switch.fan': {'state': 'off', 'attributes': {'friendly_name': 'Fan'}},
    'switch.garden_pump': {'state': 'on', 'attributes': {'friendly_name': 'Garden Pump'}},
    'sensor.living_room_temperature': {'state': '21.4', 'attributes': {
        'friendly_name': 'Living Room', 'unit_of_measurement': '°C', 'device_class': 'temperature'}},
    'sensor.outdoor_temperature': {'state': '9.8', 'attributes': {
        'friendly_name': 'Outdoors', 'unit_of_measurement': '°C', 'device_class': 'temperature'}},
    'sensor.humidity': {'state': '54', 'attributes': {
        'friendly_name': 'Humidity', 'unit_of_measurement': '%', 'device_class': 'humidity'}},
    'sensor.solar_power': {'state': '2.3', 'attributes': {
        'friendly_name': 'Solar', 'unit_of_measurement': 'kW', 'device_class': 'power'}},
    'binary_sensor.front_door': {'state': 'off', 'attributes': {'friendly_name': 'Front Door',
                                                                 'device_class': 'door'}},
}
NOW = time.struct_time((2026, 11, 20, 19, 30, 0, 4, 324, 0))


class Screen:
    def __init__(self, size):
        self.size = size

    def show(self, image, box=None):
        pass


def render(size, pages, name):
    p = panel.Panel(Screen(size), state=STATES.get, now=lambda: NOW)
    p.set_pages(pages)
    p.show_all()
    p.image.save(Path(__file__).parent / name)
    print('wrote', name)


def T(entity_id, **kw):
    return panel.Tile(entity_id, icon='auto', **kw)


HOME = panel.Page('Home', [
    T('light.living_room'), T('light.kitchen'), T('light.hallway'), T('light.bedroom'), T('light.desk_strip'),
    T('switch.fan'), T('sensor.living_room_temperature'), T('sensor.outdoor_temperature'), T('sensor.humidity'),
    T('sensor.solar_power'), T('binary_sensor.front_door'), T('switch.garden_pump')])
ROOMS = panel.Page('Rooms', [
    T('light.living_room', group='Living room'), T('sensor.living_room_temperature', group='Living room'),
    T('light.kitchen', group='Kitchen'), T('switch.fan', group='Kitchen'),
    T('light.bedroom', group='Bedroom'), T('light.desk_strip', group='Office')], layout='rooms')
CLIMATE = panel.Page('Climate', [
    T('sensor.living_room_temperature', size='2x2', show='gauge'), T('sensor.outdoor_temperature', size='2x2'),
    T('sensor.humidity', size='2x1', show='gauge'), T('sensor.solar_power', size='2x1')])

render((800, 480), [HOME, ROOMS, CLIMATE], 'home.png')
render((480, 800), [HOME, ROOMS, CLIMATE], 'home-portrait.png')
p = panel.Panel(Screen((800, 480)), state=STATES.get, now=lambda: NOW)
p.set_pages([ROOMS, HOME, CLIMATE]); p.show_all(); p.image.save(Path(__file__).parent / 'rooms.png'); print('wrote rooms.png')
p.set_pages([CLIMATE, HOME, ROOMS]); p.show_all(); p.image.save(Path(__file__).parent / 'climate.png'); print('wrote climate.png')
