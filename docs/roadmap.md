# Roadmap

Juggle HA Control Panel is a Juggle OS app for a Pi with the official 7" Touch Display: a panel on the wall that
shows Home Assistant's lights and sensors and controls them by touch. Its web page (App Base's) is where it's set
up: the Home Assistant connection, what the screen shows, and the screen's own settings. Private until 1.0, then
public.

## Design

### One app, three jobs

A Juggle OS app on App Base (vendored in `app/base/`, as Juggle Hello's), in one Python process with one asyncio
loop:

- **The web page and API** (App Base): the Device, Wi-Fi and MQTT tabs, and the app's own: Home Assistant, Screen
  and Tiles.
- **The Home Assistant connection**: the state of the entities the screen shows, kept up to date, and the actions
  touches ask for.
- **The screen**: draws the tiles, reads the touch screen, and redraws what changed.

### Drawing to the screen

Checked on the Pi 2 (2026-11-01, Juggle OS v1.1's development build, the display in portrait and landscape):

- **pygame isn't used.** Debian's `python3-pygame` brings SDL2 with Mesa (LLVM 19 for its software renderer),
  Wayland and X11 libraries and numpy: 238 MB, on a root partition of 1.2 GB kept deliberately small.
- **Pillow draws, the app writes the framebuffer.** Debian's `python3-pil` is 6 MB. The app draws the screen as a
  Pillow image (rounded rectangles, anti-aliased text in Pillow's own scalable font, so no font package), turns it
  to match the display's rotation, converts it to the framebuffer's RGB565, and writes it to `/dev/fb0` through
  `mmap`, as the console logo does. Pillow 11 has no RGB565 packer any more, so the two bytes of each pixel are made
  with its channel operations (`point`, `ImageChops.add`) and interleaved by `Image.merge("LA", ...)`, all in C.
- **Measured**: the whole 480×800 screen drawn in 32 ms and written in about 118 ms (mostly the conversion). A touch
  redraws only what it changed (a tile is about a seventh of the screen).
- **Touch** comes straight from the touch screen's input device (`/dev/input/event*`, found by name in
  `/proc/bus/input/devices`), read in pure Python (`struct`), so nothing compiled is needed. Juggle OS turns its
  coordinates with the display, so they match what the app draws.
- **Rotation**: Juggle OS's (`display-rotation`, from App Base's Device tab); the app reads it from
  `app-request settings` and turns its image to match. The layout follows the screen's shape: landscape (800×480)
  for now, at 180 degrees as the panel is mounted, and portrait (480×800) later.
- **Tearing**: the framebuffer has no vsync. Not seen as a problem for a control panel; to be watched.

### What Juggle OS needs (1.1)

Planned in the app contract as the `display` manifest setting; added to Juggle OS 1.1 with the display's rotation:

- **`"display": true`** gives the screen to the app: no login screen, console logo or cursor on it while the app
  runs (tty1 in graphics mode), and the console back when the app stops. The app user already has `/dev/fb0` and
  `/dev/input` (the `video` and `input` groups).
- **Pillow** (`python3-pil`) in the image, as a library for apps.
- **The backlight** (`/sys/class/backlight/*/brightness` and `bl_power`) writable by the app, to dim and blank the
  screen.

The app says `"juggle": "1.1"` and `"display": true`.

### Home Assistant

- **The WebSocket API** (`ws://<address>:8123/api/websocket`) with a long-lived access token: `auth`, then
  `get_states` for the start, `subscribe_events` for `state_changed` (each tile's entity), and `call_service`
  (`light.toggle`, `light.turn_on` with `brightness_pct`). It reconnects by itself, with a growing wait, and the
  screen and the page say when it isn't connected.
- **The address and token are settings**, on the app's page. The token is kept in the app's state on the Pi (root and
  the app can read it), and like the web password it's never sent back to the page, only whether one is set. Neither
  is in this repository.
- **The client** is the app's own, small, on asyncio, as App Base's MQTT client is: the opening handshake, text
  frames, fragments, ping and pong, close. Plain `ws://` on the home network; `wss://` could come later.
- **Through Home Assistant only**, at first: the Earthstorm lights (Juggle Unicorn, PlasmaStick) are in it already,
  through MQTT discovery. Talking to them directly when Home Assistant is down could come later.

### The screen

- **Tiles** in a grid, as many across as fit (four in landscape, two in portrait): a **light** (its name and state;
  a tap toggles it, a long press opens its brightness), a **sensor** (its state and unit), and the **clock** (time
  and date, at the top).
- **Chosen on the web page**: the Tiles tab lists Home Assistant's lights and sensors (the page asks the app, which
  asks Home Assistant), and the chosen ones go in order. A name of its own per tile, or Home Assistant's.
- **Built for a finger**: tiles at least 80 px each way, a dark theme, and a press shown at once.
- **The screen itself**: blank after so many minutes untouched (the first touch only wakes it), and dimmer at night.
- **On a PC**, the screen opens in a window (Tkinter, from Python's standard library), with the mouse as the finger,
  so most of the work is done without a Pi.

### Not in the first version

More than one page (swiping between them), scenes, weather, cameras, other entity types (switches, covers,
thermostats), talking to the Earthstorm lights directly, and `wss://`.

## Steps

### 1. Check the screen on the Pi

Done (2026-11-01): Pillow and the framebuffer as above, in portrait and in landscape, with touch; pygame ruled out
by its size.

### 2. Juggle OS 1.1: the display for apps

In the juggle-os repository (with the display's rotation, on its `v1.1` branch): `"display": true`, Pillow in the
image, the backlight for the app, each checked by `checks.sh` on the Pi.

### 3. The app's screen

From Juggle Hello, renamed: the screen module (the framebuffer and the PC's window, touch, rotation, redrawing only
what changed) with the clock and a test tile, on the Pi and on a PC. Tests for the drawing and the touches (Pillow
on the PC).

### 4. Home Assistant

The WebSocket client, the connection's settings on the page, its state on the page (a health chip) and the screen,
and reconnecting. Tests against a stand-in server.

### 5. Tiles

Light and sensor tiles, their brightness and states, chosen and ordered on the Tiles tab.

### 6. The screen's settings

Blanking after a time, waking on touch, dimming at night, the brightness.

### 7. 1.0

A read through, the README, the history checked for anything personal (`/check-public`), then public.
