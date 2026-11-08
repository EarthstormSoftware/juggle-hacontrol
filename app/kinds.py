"""What kind of thing a Home Assistant entity is, from its domain and device class (a motion sensor, a temperature
sensor, a light): what its states are called (a motion sensor's on is "Detected"), its icon, and the range a gauge
shows for it.

Home Assistant gives the device class as an attribute; entities without one are plain sensors, binary sensors,
lights or switches.
"""
# A binary sensor's device class: what its on and off are called, and its icon
BINARY = {
    'motion': ('Detected', 'Clear', 'motion'),
    'occupancy': ('Detected', 'Clear', 'motion'),
    'presence': ('Home', 'Away', 'motion'),
    'vibration': ('Detected', 'Clear', 'motion'),
    'door': ('Open', 'Closed', 'door'),
    'garage_door': ('Open', 'Closed', 'door'),
    'opening': ('Open', 'Closed', 'door'),
    'window': ('Open', 'Closed', 'window'),
    'moisture': ('Wet', 'Dry', 'drop'),
    'smoke': ('Smoke', 'Clear', 'alert'),
    'gas': ('Gas', 'Clear', 'alert'),
    'carbon_monoxide': ('Detected', 'Clear', 'alert'),
    'sound': ('Detected', 'Clear', 'alert'),
    'problem': ('Problem', 'OK', 'alert'),
    'safety': ('Unsafe', 'Safe', 'alert'),
    'tamper': ('Tampered', 'Clear', 'alert'),
    'battery': ('Low', 'Normal', 'battery'),
    'battery_charging': ('Charging', 'Not charging', 'battery'),
    'connectivity': ('Connected', 'Disconnected', 'signal'),
    'plug': ('Plugged in', 'Unplugged', 'plug'),
    'power': ('On', 'Off', 'bolt'),
    'running': ('Running', 'Stopped', 'bolt'),
    'light': ('Light', 'Dark', 'sun'),
    'lock': ('Unlocked', 'Locked', 'lock'),
    'heat': ('Hot', 'Normal', 'thermometer'),
    'cold': ('Cold', 'Normal', 'thermometer'),
}
# A sensor's device class: its icon, and the range a gauge shows (by unit where it depends on it), or None
SENSOR = {
    'temperature': ('thermometer', {'°C': (0, 30), '°F': (32, 86)}),
    'humidity': ('drop', (0, 100)),
    'moisture': ('drop', (0, 100)),
    'battery': ('battery', (0, 100)),
    'illuminance': ('sun', (0, 1000)),
    'power': ('bolt', {'W': (0, 3000), 'kW': (0, 3)}),
    'energy': ('bolt', None),
    'voltage': ('bolt', None),
    'current': ('bolt', None),
    'pressure': ('gauge', {'hPa': (950, 1050), 'mbar': (950, 1050)}),
    'atmospheric_pressure': ('gauge', {'hPa': (950, 1050), 'mbar': (950, 1050)}),
    'carbon_dioxide': ('air', (400, 2000)),
    'pm25': ('air', (0, 75)),
    'pm10': ('air', (0, 100)),
    'volatile_organic_compounds': ('air', None),
    'aqi': ('air', (0, 300)),
    'signal_strength': ('signal', {'dBm': (-100, -30)}),
    'timestamp': ('clock', None),
    'duration': ('clock', None),
}
# The icons a tile can have (icons.py draws them), with names for the page
ICONS = ('bulb', 'plug', 'thermometer', 'drop', 'motion', 'door', 'window', 'battery', 'sun', 'bolt', 'alert', 'clock',
         'gauge', 'signal', 'lock', 'air')
DOMAIN_ICONS = {'light': 'bulb', 'switch': 'plug', 'sensor': 'gauge', 'binary_sensor': 'alert', 'cover': 'window',
                'weather': 'sun'}
DOMAIN_NAMES = {'light': 'Light', 'switch': 'Switch', 'sensor': 'Sensor', 'binary_sensor': 'Binary sensor',
                'cover': 'Blind', 'weather': 'Weather'}
# Binary sensors whose on means something's wrong, and those whose off does (the rest: on is merely active)
WRONG_WHEN_ON = ('problem', 'safety', 'smoke', 'gas', 'carbon_monoxide', 'tamper', 'moisture', 'battery', 'heat', 'cold')
WRONG_WHEN_OFF = ('connectivity',)
# Home Assistant's weather conditions, where its word doesn't read as one
WEATHER = {'clear-night': 'Clear', 'partlycloudy': 'Partly cloudy', 'lightning-rainy': 'Thunderstorm',
           'snowy-rainy': 'Sleet', 'windy-variant': 'Windy', 'exceptional': 'Severe'}


def device_class(state):
    return ((state or {}).get('attributes') or {}).get('device_class')


def describe(domain, device_class):
    """What it is, for the page: "Light", "Motion sensor", "Temperature sensor", "Sensor"."""
    if domain in ('sensor', 'binary_sensor') and device_class:
        return device_class.replace('_', ' ').capitalize() + ' sensor'
    return DOMAIN_NAMES.get(domain, domain)


def icon(domain, device_class):
    """The icon that suits it."""
    if domain == 'binary_sensor' and device_class in BINARY:
        return BINARY[device_class][2]
    if domain == 'sensor' and device_class in SENSOR:
        return SENSOR[device_class][0]
    return DOMAIN_ICONS.get(domain, 'gauge')


def on_off(device_class):
    """What a binary sensor's on and off are called."""
    return BINARY[device_class][:2] if device_class in BINARY else ('On', 'Off')


def mood(device_class, on):
    """How a binary sensor stands out: 'alert' when it says something's wrong, 'lit' when active, otherwise 'calm'."""
    if device_class in WRONG_WHEN_OFF:
        return 'calm' if on else 'alert'
    if device_class in WRONG_WHEN_ON:
        return 'alert' if on else 'calm'
    return 'lit' if on else 'calm'


def weather(condition):
    """A weather entity's state in words."""
    return WEATHER.get(condition, condition.replace('-', ' ').capitalize())


def gauge_range(device_class, unit):
    """The range a gauge shows for a sensor (low, high), or None when its kind doesn't say."""
    found = SENSOR.get(device_class, (None, None))[1]
    if isinstance(found, dict):
        return found.get(unit)
    if found is None and unit == '%':
        return 0, 100
    return found
