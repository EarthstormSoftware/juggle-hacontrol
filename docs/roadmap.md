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
  `subscribe_entities` for just the tiles' entities (their state at once, then only what changes in them: not
  every `state_changed` in the house, too much for a Pi 2 to parse), `get_states` only when the page lists them all
  to choose from, and `call_service`
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

- **A bar along the top** (asked for 2026-11-01, in place of a large clock: the tiles matter more): the date and
  time, and what's wrong (Home Assistant not connected, an action that failed) in place of the date.
- **Tiles** filling the rest, as large as they can be: the grid's columns and rows are chosen for the number of
  tiles and the screen's shape (five in landscape are three and two), never taller than wide. A **light** or
  **switch** (a tap toggles it; a light shows its brightness, and a long press opens a slider for it), a **sensor**
  (its state and unit, large; a timestamp as how long ago), or a **binary sensor** (on or off). A name wraps onto a
  second line and shrinks to fit, keeping words whole if it can, then breaking them where they join (CounterTopLeft
  at its capitals), and only then anywhere.
- **Pages** (asked for 2026-11-01): up to six, each with a name and up to eight tiles. With more than one, the bar
  has a tab for each in place of the date, and a swipe across changes the page. Every page's entities are watched,
  so changing the page is at once.
- **Chosen on the web page**: the Screen tab has the pages, each page's tiles in order (a name of its own per tile,
  or Home Assistant's), and Home Assistant's lights, switches and sensors to add (the page asks the app, which asks
  Home Assistant), filtered by what's typed.
- **Built for a finger**: large tiles, a dark theme, and a press shown at once.
- **The screen itself**: dark (the backlight off) after so many minutes untouched, 5 by default (0 for never), the
  first touch only waking it; and its brightness. Both on the Screen tab. Dimmer at night could come later.
- **On a PC**, the screen opens in a window (Tkinter, from Python's standard library), with the mouse as the finger,
  so most of the work is done without a Pi.

### Not in the first version

Scenes, weather, cameras, other entity types (covers, thermostats), dimming at night, talking to the Earthstorm
lights directly, and `wss://`.

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

Done (2026-11-01), connected to Home Assistant 2024.8.1.

### 5. Tiles

Light, switch and sensor tiles, their brightness and states, chosen and ordered on the page. Done (2026-11-01),
then (the same day, asked for on seeing them) the bar in place of the clock, tiles sized to fill the screen with
their text fitted, and pages.

### 6. The screen's settings

Dark after a time and waking on touch, and the brightness: done (2026-11-01). Dimming at night later.

### 7. 1.0

A read through, the README, the history checked for anything personal (`/check-public`), then public.
