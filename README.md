# Juggle HA Control Panel

A [Juggle OS](https://github.com/EarthstormSoftware/juggle-os) app for a Raspberry Pi with the official 7" Touch
Display: a panel on the wall showing Home Assistant's lights and sensors, controlled by touch. Its web page is where
it's set up: the Home Assistant connection, what the screen shows, and the screen's own settings.

It's built on [App Base](https://github.com/EarthstormSoftware/app-base), from
[Juggle Hello](https://github.com/EarthstormSoftware/juggle-hello). The design and the steps are in
[docs/roadmap.md](docs/roadmap.md).

**Status:** started. It's still Juggle Hello's greeting while the screen is written.

## What it needs

A Pi running Juggle OS with the official 7" Touch Display, and Home Assistant on the same network with a long-lived
access token (your profile in Home Assistant, Security).

## Deploying it

On Windows, with the Pi set up by `juggle flash` (so SSH works with your key):

```powershell
.\deploy.ps1 <name>
```

Then its page is at `http://<name>.local`. Once it's running, `.\deploy.ps1 <name> -WiFi` sends a new version to the
app itself, without SSH.

## Tests

`py -m pytest` (Python 3.11 or later).

## Licence

MIT. See [LICENSE](LICENSE). Microdot is MIT too: see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
