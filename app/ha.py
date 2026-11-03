"""Home Assistant over its WebSocket API (docs/roadmap.md, Home Assistant): the states of the entities the screen
shows, kept up to date, the services touches call, and a sensor's history when it's asked for.

The connection authenticates with a long-lived access token, then subscribes to just the entities watched
(subscribe_entities: their state and attributes at once, then only what changes in them), so a busy Home Assistant
doesn't send the Pi every change in the house. The list of all of them, for choosing tiles, is fetched when it's
asked for (get_states). It reconnects by itself, waiting longer each time it fails (up to a few minutes), and at once
when its settings change.

The WebSocket client is this module's own, on asyncio (as App Base's MQTT client is): the opening handshake, text
frames and fragments, ping and pong, close. Plain ws:// on the home network.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import struct
import time
from datetime import datetime, timezone

from base.log import Log
from kinds import describe, icon

TAG = 'HA'
PATH = '/api/websocket'
PORT = 8123
TIMEOUT = 10
# A week's history can take Home Assistant a while
HISTORY_TIMEOUT = 30
# How often the connection is checked (Home Assistant answers a ping with a pong)
PING_EVERY = 30
# Waits between attempts after failures: doubling from the first, up to the last
RETRY_FIRST, RETRY_MOST = 2, 300
LARGEST_MESSAGE = 16 * 1024 * 1024
GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
# Home Assistant's address, as typed on the page: a host name or IPv4 address, with a port and http:// or ws:// if
# wanted (https:// and wss:// aren't supported yet)
ADDRESS = re.compile(r'(?:(?:http|ws)://)?([A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)(?::([0-9]{1,5}))?/?')


def parse_address(text):
    """(host, port) from Home Assistant's address as typed, or None if it isn't one."""
    found = ADDRESS.fullmatch(text.strip())
    if not found:
        return None
    port = int(found.group(2) or PORT)
    return (found.group(1), port) if 0 < port < 65536 else None


def check_address(value):
    """A Setting check: why the address can't be used, or None."""
    if not isinstance(value, str):
        return 'must be text'
    if value.strip() and parse_address(value) is None:
        return 'must be an address such as 192.168.1.10, homeassistant.local:8123 or http://192.168.1.10:8123 ' \
               '(https isn\'t supported yet)'
    return None


class WebSocketError(Exception):
    pass


class WebSocket:
    """A WebSocket client connection, for text messages."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    @classmethod
    async def connect(cls, host, port, path, timeout=TIMEOUT):
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write('GET {} HTTP/1.1\r\nHost: {}:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                     'Sec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n'.format(path, host, port, key).encode())
        try:
            await writer.drain()
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            raise WebSocketError('no answer to the WebSocket handshake')
        lines = head.decode('latin-1').split('\r\n')
        headers = {name.strip().lower(): value.strip()
                   for name, _, value in (line.partition(':') for line in lines[1:] if line)}
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if lines[0].split(' ')[1:2] != ['101'] or headers.get('sec-websocket-accept') != accept:
            writer.close()
            raise WebSocketError('not a WebSocket: {}'.format(lines[0]))
        return cls(reader, writer)

    async def _send_frame(self, opcode, payload):
        """A frame, masked, as a client's must be."""
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = struct.pack('!BB', 0x80 | opcode, 0x80 | length)
        elif length < 65536:
            header = struct.pack('!BBH', 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack('!BBQ', 0x80 | opcode, 0x80 | 127, length)
        masked = (int.from_bytes(payload, 'big') ^ int.from_bytes((mask * (length // 4 + 1))[:length], 'big')
                  ).to_bytes(length, 'big') if length else b''
        self.writer.write(header + mask + masked)
        await self.writer.drain()

    async def send(self, text):
        await self._send_frame(0x1, text.encode())

    async def receive(self):
        """The next text message. Answers pings on the way; raises ConnectionError when the connection closes."""
        parts = []
        size = 0
        while True:
            try:
                first, second = await self.reader.readexactly(2)
                length = second & 0x7F
                if length == 126:
                    length, = struct.unpack('!H', await self.reader.readexactly(2))
                elif length == 127:
                    length, = struct.unpack('!Q', await self.reader.readexactly(8))
                mask = await self.reader.readexactly(4) if second & 0x80 else None
                if size + length > LARGEST_MESSAGE:
                    raise WebSocketError('a message larger than {} bytes'.format(LARGEST_MESSAGE))
                payload = await self.reader.readexactly(length)
            except asyncio.IncompleteReadError:
                raise ConnectionError('the connection closed')
            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            opcode = first & 0x0F
            if opcode == 0x8:
                raise ConnectionError('Home Assistant closed the connection')
            if opcode == 0x9:
                await self._send_frame(0xA, payload)
            elif opcode in (0x0, 0x1):
                parts.append(payload)
                size += length
                if first & 0x80:
                    return b''.join(parts).decode()

    def close(self):
        self.writer.close()


class AuthError(Exception):
    pass


class RequestError(Exception):
    pass


class HomeAssistant:
    """The connection to Home Assistant. changed(entity_ids) is called when watched entities' states change (all of
    them, as None, when the connection comes or goes)."""

    def __init__(self, changed=lambda entity_ids: None):
        self.changed = changed
        self.address, self.token = '', ''
        self.watched = []
        # The watched entities: {entity_id: {"state", "attributes"}}
        self.states = {}
        self.status = 'not set up'
        self.connected = False
        self.version = None
        self._socket = None
        self._pending = {}
        self._next_id = 1
        self._subscription = None
        self._wake = asyncio.Event()

    def configure(self, address, token):
        """New settings: used at once (a connection made with the old ones is closed)."""
        if (address, token) != (self.address, self.token):
            self.address, self.token = address, token
            self._restart()

    def watch(self, entity_ids):
        """The entities to keep the states of (the tiles')."""
        if list(entity_ids) != self.watched:
            self.watched = list(entity_ids)
            self._restart()

    def _restart(self):
        if self._socket:
            self._socket.close()
        self._wake.set()

    async def run(self):
        retry = RETRY_FIRST
        while True:
            self._wake.clear()
            if not self.address.strip() or not self.token:
                self._set_status('not set up')
                await self._wake.wait()
                continue
            try:
                await self._session()
            except AuthError as e:
                self._set_status('the token was refused: {}'.format(e))
                retry = RETRY_MOST
            except (OSError, WebSocketError, RequestError, asyncio.TimeoutError, ValueError, KeyError) as e:
                if self._wake.is_set():
                    continue  # closed on purpose, for new settings or entities: straight back, saying nothing
                if self.connected:  # it had worked: try again soon
                    retry = RETRY_FIRST
                self._set_status('not connected: {}'.format(e or type(e).__name__))
            if not self._wake.is_set():
                try:
                    await asyncio.wait_for(self._wake.wait(), retry)
                except asyncio.TimeoutError:
                    pass
                retry = min(retry * 2, RETRY_MOST)

    def _set_status(self, status):
        connected = status == 'connected'
        if status != self.status:
            (Log.info if status in ('connected', 'connecting') else Log.warn)(TAG, 'Home Assistant: {}'.format(status))
        self.status = status
        if connected != self.connected:
            self.connected = connected
            if not connected:
                self.states = {}
            self.changed(None)

    async def _session(self):
        host, port = parse_address(self.address)
        if not self.connected:  # coming back on purpose, the states shown stay until the new ones come
            self._set_status('connecting')
        socket = await WebSocket.connect(host, port, PATH)
        try:
            await self._authenticate(socket)
            self._socket = socket
            reader = asyncio.ensure_future(self._read(socket))
            try:
                if self.watched:
                    self._subscription = None
                    await self.request({'type': 'subscribe_entities', 'entity_ids': self.watched})
                self._set_status('connected')
                while True:
                    done, _ = await asyncio.wait([reader], timeout=PING_EVERY)
                    if done:
                        reader.result()  # its error
                    await self.request({'type': 'ping'})
            finally:
                reader.cancel()
        finally:
            self._socket = None
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError('the connection closed'))
            self._pending = {}
            socket.close()

    async def _authenticate(self, socket):
        hello = json.loads(await asyncio.wait_for(socket.receive(), TIMEOUT))
        if hello.get('type') != 'auth_required':
            raise WebSocketError("Home Assistant didn't ask to authenticate")
        await socket.send(json.dumps({'type': 'auth', 'access_token': self.token}))
        answer = json.loads(await asyncio.wait_for(socket.receive(), TIMEOUT))
        if answer.get('type') != 'auth_ok':
            raise AuthError(answer.get('message') or answer.get('type'))
        self.version = answer.get('ha_version')

    async def _read(self, socket):
        while True:
            message = json.loads(await socket.receive())
            kind = message.get('type')
            if kind in ('result', 'pong'):
                future = self._pending.pop(message.get('id'), None)
                if future and not future.done():
                    future.set_result(message)
            elif kind == 'event':
                self._event(message.get('event') or {})

    def _event(self, event):
        """A subscribe_entities event: entities added ("a", whole), changed ("c": "+" what's new, "-" attributes
        gone) or removed ("r")."""
        touched = []
        for entity_id, compressed in (event.get('a') or {}).items():
            self.states[entity_id] = {'state': compressed.get('s'), 'attributes': compressed.get('a') or {}}
            touched.append(entity_id)
        for entity_id, diff in (event.get('c') or {}).items():
            state = self.states.setdefault(entity_id, {'state': None, 'attributes': {}})
            added, gone = diff.get('+') or {}, diff.get('-') or {}
            if 's' in added:
                state['state'] = added['s']
            state['attributes'].update(added.get('a') or {})
            for name in gone.get('a') or ():
                state['attributes'].pop(name, None)
            touched.append(entity_id)
        for entity_id in event.get('r') or ():
            self.states.pop(entity_id, None)
            touched.append(entity_id)
        if touched:
            self.changed(touched)

    async def request(self, message, timeout=TIMEOUT):
        """Sends a command and returns Home Assistant's answer. Raises RequestError if it failed, ConnectionError if
        there's no connection."""
        if self._socket is None:
            raise ConnectionError('not connected to Home Assistant')
        message = dict(message, id=self._next_id)
        self._next_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[message['id']] = future
        await self._socket.send(json.dumps(message))
        answer = await asyncio.wait_for(future, timeout)
        if answer.get('type') == 'result' and not answer.get('success'):
            raise RequestError((answer.get('error') or {}).get('message') or 'Home Assistant refused it')
        return answer.get('result')

    async def call_service(self, domain, service, entity_id, **data):
        """Calls a service on an entity, such as light.toggle."""
        return await self.request({'type': 'call_service', 'domain': domain, 'service': service,
                                   'service_data': data, 'target': {'entity_id': entity_id}})

    async def entities(self, domains=('light', 'sensor', 'binary_sensor', 'switch')):
        """Every entity in those domains, for choosing tiles: [{"entity_id", "name", "state", "unit", "kind" (what
        it is: "Motion sensor"), "icon" (the one that suits it), "numeric"}] by name."""
        found = []
        for state in await self.request({'type': 'get_states'}):
            domain = state['entity_id'].split('.', 1)[0]
            if domain in domains:
                attributes = state.get('attributes') or {}
                device_class = attributes.get('device_class')
                found.append({'entity_id': state['entity_id'],
                              'name': attributes.get('friendly_name') or state['entity_id'],
                              'state': state.get('state'), 'unit': attributes.get('unit_of_measurement'),
                              'kind': describe(domain, device_class), 'icon': icon(domain, device_class),
                              'numeric': domain == 'sensor' and (attributes.get('state_class') is not None
                                                                 or is_number(state.get('state')))})
        return sorted(found, key=lambda entity: entity['name'].lower())

    async def history(self, entity_id, hours):
        """An entity's states over the last hours: [(when, state)] oldest first, when in seconds since 1970, the
        first being its state as the time began."""
        start = datetime.fromtimestamp(time.time() - hours * 3600, timezone.utc).isoformat()
        found = await self.request({'type': 'history/history_during_period', 'start_time': start,
                                    'entity_ids': [entity_id], 'minimal_response': True, 'no_attributes': True,
                                    'significant_changes_only': False}, timeout=HISTORY_TIMEOUT)
        return [(entry.get('lu') or entry.get('lc'), entry.get('s')) for entry in (found or {}).get(entity_id, [])
                if (entry.get('lu') or entry.get('lc')) is not None]


def is_number(text):
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True
