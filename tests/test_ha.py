"""The Home Assistant connection (ha.py), against a stand-in Home Assistant on this PC: a small WebSocket server that
speaks its protocol (auth, subscribe_entities, get_states, call_service, ping)."""
import asyncio
import base64
import hashlib
import json
import struct

import pytest

import ha

TOKEN = 'good-token'
STATES = [
    {'entity_id': 'light.kitchen', 'state': 'on', 'attributes': {'friendly_name': 'Kitchen', 'brightness': 200}},
    {'entity_id': 'sensor.hall_temperature', 'state': '19.5',
     'attributes': {'friendly_name': 'Hall Temperature', 'unit_of_measurement': '°C', 'device_class': 'temperature',
                    'state_class': 'measurement'}},
    {'entity_id': 'automation.night', 'state': 'on', 'attributes': {'friendly_name': 'Night'}},
    {'entity_id': 'light.attic', 'state': 'off', 'attributes': {'friendly_name': 'attic'}},
]


class FakeHomeAssistant:
    def __init__(self, token=TOKEN, states=STATES, fragment=False):
        self.token, self.states, self.fragment = token, states, fragment
        self.received = []
        self.connections = 0
        self.writer = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0)
        self.address = '127.0.0.1:{}'.format(self.server.sockets[0].getsockname()[1])
        return self

    async def handle(self, reader, writer):
        head = (await reader.readuntil(b'\r\n\r\n')).decode()
        key = next(line.split(':', 1)[1].strip() for line in head.split('\r\n')
                   if line.lower().startswith('sec-websocket-key'))
        accept = base64.b64encode(hashlib.sha1((key + ha.GUID).encode()).digest()).decode()
        writer.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                     'Sec-WebSocket-Accept: {}\r\n\r\n'.format(accept).encode())
        self.writer = writer
        self.connections += 1
        await self.send({'type': 'auth_required', 'ha_version': '2026.11.0'})
        auth = await self.receive(reader)
        if auth.get('access_token') != self.token:
            await self.send({'type': 'auth_invalid', 'message': 'Invalid access token or password'})
            writer.close()
            return
        await self.send({'type': 'auth_ok', 'ha_version': '2026.11.0'})
        try:
            while True:
                message = await self.receive(reader)
                self.received.append(message)
                kind, number = message['type'], message['id']
                if kind == 'ping':
                    await self.send({'id': number, 'type': 'pong'})
                elif kind == 'subscribe_entities':
                    await self.send({'id': number, 'type': 'result', 'success': True, 'result': None})
                    watched = {s['entity_id']: {'s': s['state'], 'a': s['attributes'], 'lu': 1.0}
                               for s in self.states if s['entity_id'] in message['entity_ids']}
                    await self.send({'id': number, 'type': 'event', 'event': {'a': watched}})
                elif kind == 'history/history_during_period':
                    found = {entity_id: [{'s': '18.5', 'a': {}, 'lu': 1000.0}, {'s': '19.0', 'lu': 1600.5},
                                         {'s': 'unavailable', 'lc': 2000.0}]
                             for entity_id in message['entity_ids']}
                    await self.send({'id': number, 'type': 'result', 'success': True, 'result': found})
                elif kind == 'get_states':
                    await self.send({'id': number, 'type': 'result', 'success': True, 'result': self.states})
                elif kind == 'call_service':
                    if message['domain'] == 'light':
                        await self.send({'id': number, 'type': 'result', 'success': True, 'result': {'context': {}}})
                    else:
                        await self.send({'id': number, 'type': 'result', 'success': False,
                                         'error': {'code': 'not_found', 'message': 'Service not found.'}})
        except asyncio.IncompleteReadError:
            pass

    async def send(self, message):
        """A message as Home Assistant sends it: unmasked frames, in two fragments if asked."""
        payload = json.dumps(message).encode()
        parts = [payload[:len(payload) // 2], payload[len(payload) // 2:]] if self.fragment else [payload]
        for index, part in enumerate(parts):
            opcode = 0x1 if index == 0 else 0x0
            fin = 0x80 if index == len(parts) - 1 else 0
            length = len(part)
            if length < 126:
                header = struct.pack('!BB', fin | opcode, length)
            elif length < 65536:
                header = struct.pack('!BBH', fin | opcode, 126, length)
            else:
                header = struct.pack('!BBQ', fin | opcode, 127, length)
            self.writer.write(header + part)
        await self.writer.drain()

    async def event(self, event):
        await self.send({'id': 1, 'type': 'event', 'event': event})

    @staticmethod
    async def receive(reader):
        first, second = await reader.readexactly(2)
        assert second & 0x80, "a client's frames are masked"
        length = second & 0x7F
        if length == 126:
            length, = struct.unpack('!H', await reader.readexactly(2))
        elif length == 127:
            length, = struct.unpack('!Q', await reader.readexactly(8))
        mask = await reader.readexactly(4)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(await reader.readexactly(length)))
        return json.loads(payload)


async def until(condition, seconds=3):
    for _ in range(int(seconds / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError('timed out')


def run(test):
    async def main():
        server = await FakeHomeAssistant().start()
        await test(server)
    asyncio.run(main())


def connected(server, watched=(), **kwargs):
    changes = []
    client = ha.HomeAssistant(changed=changes.append)
    client.watch(watched)
    client.configure(server.address, kwargs.get('token', TOKEN))
    return client, changes, asyncio.ensure_future(client.run())


def test_it_connects_and_keeps_the_watched_entities_states():
    async def test(server):
        client, changes, task = connected(server, ['light.kitchen', 'sensor.hall_temperature'])
        await until(lambda: client.connected and 'sensor.hall_temperature' in client.states)
        assert client.status == 'connected' and client.version == '2026.11.0'
        assert server.received[0] == {'type': 'subscribe_entities', 'id': 1,
                                      'entity_ids': ['light.kitchen', 'sensor.hall_temperature']}
        assert client.states['light.kitchen'] == {'state': 'on', 'attributes': {'friendly_name': 'Kitchen',
                                                                              'brightness': 200}}
        assert None in changes and ['light.kitchen', 'sensor.hall_temperature'] in changes

        # A change: the new state and attribute, and one gone
        await server.event({'c': {'light.kitchen': {'+': {'s': 'off', 'a': {'color_mode': None}, 'lu': 2.0},
                                                    '-': {'a': ['brightness']}}}})
        await until(lambda: client.states['light.kitchen']['state'] == 'off')
        assert client.states['light.kitchen']['attributes'] == {'friendly_name': 'Kitchen', 'color_mode': None}
        assert changes[-1] == ['light.kitchen']

        await server.event({'r': ['sensor.hall_temperature']})
        await until(lambda: 'sensor.hall_temperature' not in client.states)
        task.cancel()
    run(test)


def test_a_service_is_called_on_an_entity_and_a_refusal_says_why():
    async def test(server):
        client, _, task = connected(server)
        await until(lambda: client.connected)
        await client.call_service('light', 'turn_on', 'light.kitchen', brightness_pct=40)
        assert server.received[-1] == {'type': 'call_service', 'domain': 'light', 'service': 'turn_on',
                                       'service_data': {'brightness_pct': 40},
                                       'target': {'entity_id': 'light.kitchen'}, 'id': server.received[-1]['id']}
        with pytest.raises(ha.RequestError, match='Service not found'):
            await client.call_service('cover', 'open_cover', 'cover.garage')
        task.cancel()
    run(test)


def test_the_entities_to_choose_from_are_the_lights_sensors_and_switches_by_name():
    async def test(server):
        client, _, task = connected(server)
        await until(lambda: client.connected)
        assert [e['entity_id'] for e in await client.entities()] == ['light.attic', 'sensor.hall_temperature',
                                                                    'light.kitchen']
        assert (await client.entities())[1] == {'entity_id': 'sensor.hall_temperature', 'name': 'Hall Temperature',
                                                'state': '19.5', 'unit': '°C', 'kind': 'Temperature sensor',
                                                'icon': 'thermometer', 'numeric': True}
        assert (await client.entities())[0]['kind'] == 'Light'
        task.cancel()
    run(test)


def test_a_history_is_its_states_with_when_each_began(monkeypatch):
    monkeypatch.setattr(ha.time, 'time', lambda: 1793566800.0)

    async def test(server):
        client, _, task = connected(server)
        await until(lambda: client.connected)
        assert await client.history('sensor.hall_temperature', 6) == [(1000.0, '18.5'), (1600.5, '19.0'),
                                                                       (2000.0, 'unavailable')]
        asked = server.received[-1]
        assert asked['entity_ids'] == ['sensor.hall_temperature'] and asked['no_attributes']
        assert asked['start_time'] == '2026-11-01T15:00:00+00:00'  # six hours before
        task.cancel()
    run(test)


def test_a_refused_token_says_so_and_isnt_tried_again_soon():
    async def test(server):
        client, _, task = connected(server, token='wrong')
        await until(lambda: client.status.startswith('the token was refused'))
        assert 'Invalid access token' in client.status and not client.connected
        await asyncio.sleep(0.2)
        assert server.connections == 1
        task.cancel()
    run(test)


def test_it_reconnects_when_the_connection_drops_and_at_once_when_settings_change(monkeypatch):
    monkeypatch.setattr(ha, 'RETRY_FIRST', 0.05)

    async def test(server):
        client, changes, task = connected(server, ['light.kitchen'])
        await until(lambda: client.connected and client.states)
        server.writer.close()
        await until(lambda: not client.connected)
        assert client.states == {}  # unknown while it isn't connected
        await until(lambda: client.connected and server.connections == 2)

        client.configure(server.address, TOKEN + '2')  # another token: refused, at once
        await until(lambda: client.status.startswith('the token was refused'))
        assert server.connections == 3
        task.cancel()
    run(test)


def test_without_an_address_or_token_it_waits_for_them():
    async def test(server):
        client = ha.HomeAssistant()
        task = asyncio.ensure_future(client.run())
        await asyncio.sleep(0.05)
        assert client.status == 'not set up' and server.connections == 0
        client.configure(server.address, TOKEN)
        await until(lambda: client.connected)
        task.cancel()
    run(test)


def test_large_and_fragmented_messages_arrive_whole():
    async def test(server):
        server.states = STATES + [{'entity_id': 'sensor.n{}'.format(n), 'state': 'x' * 100,
                                   'attributes': {'friendly_name': 'N{}'.format(n)}} for n in range(1000)]
        server.fragment = True
        client, _, task = connected(server)
        await until(lambda: client.connected)
        assert len(await client.entities()) == 1003
        task.cancel()
    run(test)


@pytest.mark.parametrize('text, expected', [
    ('192.168.1.10', ('192.168.1.10', 8123)), (' homeassistant.local:8124 ', ('homeassistant.local', 8124)),
    ('http://ha.lan:8123/', ('ha.lan', 8123)), ('ws://10.0.0.2', ('10.0.0.2', 8123)),
    ('https://ha.lan', None), ('ha.lan:0', None), ('', None)])
def test_addresses(text, expected):
    assert ha.parse_address(text) == expected
