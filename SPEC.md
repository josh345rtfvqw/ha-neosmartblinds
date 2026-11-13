# Neo Smart Blinds for Home Assistant: build spec

This is the only input for building the integration. It describes what the integration does and the interfaces it has to match. It deliberately says nothing about how the code should be organised.

## Rules for whoever builds this

- Work only from this spec, Home Assistant's own documentation and source, and Neo's published API documents (below).
- Do not look at, search for, or open any existing Neo Smart Blinds Home Assistant integration. That includes `4n0nD3v3l0p3r/Home_Assistant_NeoSmartBlinds`, `mtgeekman/Home_Assistant_NeoSmartBlinds` and any fork of them, and their code, issues and release zips.
- This repo (`josh345rtfvqw/ha-neosmartblinds`) holds the current version, which this rewrite replaces. Work on `master`, but before writing anything, delete everything except `SPEC.md`, `LICENSE`, `.gitignore` and `custom_components/neosmartblinds/brand/` in one commit, without opening the files you delete. Don't read the git history, older commits, tags, releases or the deleted files at any point.
- Design the structure (files, classes, function names) yourself. Where this spec gives a name, it's an interface that users or Home Assistant rely on, and must match exactly.
- If something here is unclear, ask Josh. Don't fill the gap from another integration.

## Basics

- Custom integration, domain `neosmartblinds`, name **Neo Smart Blinds**, installed through HACS (integration category).
- Minimum Home Assistant version 2025.8. Python version as required by current Home Assistant.
- `integration_type: hub`, `iot_class: assumed_state`, config flow, no external requirements. Use Home Assistant's shared aiohttp session for HTTP.
- Everything is set up from the UI. YAML from older versions is imported once (see "Importing old YAML").
- MIT licence, copyright Josh Spires.
- Include `brand/icon.png` (256x256) and `brand/icon@2x.png` (512x512) in the integration folder. Josh will supply them.

## The controller

Source for everything in this section: Neo's API documents (version 1.8, July 2025), from help.neosmartblinds.com:

- [Local HTTP API](https://help.neosmartblinds.com/portal/api/kbArticles/414972000003758017/locale/en/attachments/8ygk312bbd60298b54311bfd0964e865c998f/content?portalId=edbsnc3f14403ccf379185be762f5beac126c0f74fc067d682dc474506fed7073ca55&inline=true)
- [Basic Open TCP API](https://help.neosmartblinds.com/portal/api/kbArticles/414972000003758017/locale/en/attachments/8ygk38d91fef701534c6e88561cbbeee3186b/content?portalId=edbsnc3f14403ccf379185be762f5beac126c0f74fc067d682dc474506fed7073ca55&inline=true)

Add both PDFs to the repo under `docs/` if Neo's terms allow, otherwise link them.

The Neo Smart Controller is on the local network. It never reports blind positions or status. It accepts one command at a time, takes at least 500 ms per command, and handles 1 to 3 connections at once (Neo recommends one). Each request is a new connection that the controller closes after replying. Commands are case-insensitive and end in CRLF.

### Command format

`ID1.ID2-CHANNEL-ACTION!MOTORCODE`, for example `021.230-04-up!bf`.

- `ID1.ID2-CHANNEL` is the blind code, entered by the user, for example `021.230-04`. ID1 and ID2 are three-digit numbers from 000 to 255. Channel is two digits: `01`–`14` for one blind, `15` for every blind in that room (the "room code"). `00` exists but not every brand supports it. Validate input against these ranges.
- `!MOTORCODE` is left off when no motor code is set.

### HTTP (default port 8838)

`GET http://<host>:<port>/neo/v1/transmit?command=<command>&id=<controller id>&hash=<hash>`

- Controller ID: 20 or more letters and digits, required for HTTP.
- Hash: optional per Neo, but always send one. 7 digits, never reused. Neo suggests the last 7 digits of the current time in milliseconds. Add 1 if it equals the last one sent.
- 200: received and transmitted. 400: command invalid. 401: controller ID not found (start re-authentication, see below). 404: wrong path. 409: hash already used, so retry once with a new hash. Any other failure: report the status.
- 10 second timeout.

### TCP (default port 8839)

Open a connection, send the command plus `\r\n`, read the echo, close. No controller ID. The controller echoes whatever it received, even invalid input, and replies before checking the command, so TCP can't report a bad command or a wrong ID. 10 second timeout.

### Pacing

Queue all commands per controller and space them at least 0.7 s apart (Neo's docs ask for at least 500 ms).

### Actions

| Action | Meaning |
|---|---|
| `up`, `dn`, `sp` | Open, close, stop (top rail) |
| `mu`, `md` | Micro-step up/down (tilt open/close), top rail |
| `01`–`99` | Go to a position. The value is percent **closed**, so Home Assistant 30% open is sent as `70`. |
| `gp` | Favourite position 1 |
| `i2` | Favourite position 2 |
| `u2`, `d2`, `o2`, `c2` | Bottom rail: open, close, micro-step up, micro-step down |
| `u3`, `d3` | Both rails: open, close |
| `u4`, `d4`, `x2` | Extended top-down/bottom-up: middle rail open, close, stop (`x2` replaces `sp`) |
| `op`, `cl` | Top-down/bottom-up only: open shades (both rails up), close shades (middle rail up, lower rail down). Not used by the cover; available through the raw command action. |
| `i1` | Intermediate position 1 (NEO motors, replaces `gp`). Available through the raw command action. |

Neo's documents use "middle rail" for rail 1, "lower rail" for rail 2 and "both" for rail 3. Motor `tb` is always top-down/bottom-up. `mb`, `ra`, `ap` and `db` are only when the motor is the top-down/bottom-up type; otherwise they use the standard set.

Which actions each blind uses:

| Rail | Standard set | Extended set |
|---|---|---|
| 1 top/middle | `up` `dn` `sp`, tilt `mu` `md` | `u4` `d4` `x2`, no tilt |
| 2 bottom | `u2` `d2` `sp`, tilt `o2` `c2` | `u2` `d2` `x2`, no tilt |
| 3 both | `u3` `d3` `sp`, no tilt | `u3` `d3` `x2`, no tilt |

### Motor codes

Shown in the UI as `code – name`. Users can also type any two-character code (`[a-z0-9]{2}`, lower-cased).

| Code | Name |
|---|---|
| bf | Bofu (standard) |
| vb | Bofu (vertical) |
| tb | Bofu top-down/bottom-up |
| no | NEO |
| rx | Raex |
| nc | Nice F-Code |
| nr | Nice 0-Code |
| k1 | A-OK (standard) |
| k2 | A-OK v2 (Louvolite) |
| k3 | A-OK v3 (Eclipse) |
| dy | Dooya (unidirectional) |
| by | Bofu/Dooya (deprecated) |
| wt | Wistar / Alpha |
| db | Dooya (bi-directional) |
| sy | Somfy RTS |
| gp | Gaposa |
| ra | Rollease ARC |
| re | Rollease EL |
| ap | AMP (Turnils) |
| sf | Sunfrere |
| rc | Ronco |
| bl | Alta Bliss |
| mb | Coulisse MotionBlinds |
| jo | Jiecang |

- Accept a `01`–`99` position: `no`, `db`, `ra`, `rb`, `ap`, `bl`, `mb`, `jo` (top rail only). Neo lists `rb` here but not in its motor table, so accept it as typed but don't add it to the dropdown.
- Can have the extended top-down/bottom-up set: `mb`, `ra`, `ap`, `db`.
- Have favourite 2: `no`, `rx`, and blinds with no motor code.

## Setup

### Controller (config entry)

Two steps:

1. **Host** and **Protocol** (HTTP or TCP, HTTP recommended because it reports errors).
2. **Port** (pre-filled 8838 for HTTP, 8839 for TCP) and **Controller ID** (required for HTTP, not used for TCP).

On submit, check a connection can be opened (TCP connect to host and port). Don't send a command. Refuse duplicates (same controller ID, or same host when there's no ID).

Entry title: `Neo Smart Controller (<host>)`. The controller is a device.

Reconfigure: change host, protocol, port and ID. Re-authentication: when HTTP returns 401, ask for the controller ID again. No notification for this case.

The controller has a **Configure** (options) screen for naming rooms: one text field per room code shared by two or more blinds. Unnamed rooms are called `Room <room code>`.

### Blinds (one subentry per blind, type `blind`)

**Add blind** on the controller entry. Fields:

| Field | Notes |
|---|---|
| Name | Required |
| Blind code | Required, format above. Duplicates of the same blind code, motor code and rail on one controller are refused. |
| Motor code | Optional, dropdown plus free text |
| Rail | 1 top/middle (default), 2 bottom, 3 both |
| Extended top-down/bottom-up commands | Off by default. Only allowed with `mb`, `ra`, `ap`, `db`. |
| Supports tilt | Off by default |
| Positioning mode | 0 *Open and close only*, 1 *Blind moves to the position*, 2 *Timed position (estimated)*. Mode 1 is only allowed on the top rail, without the extended set, and with a motor code that accepts positions (or no motor code). |
| Close time | Seconds, fully open to fully closed, default 20 |
| Open time | Optional, seconds fully closed to fully open. Empty means same as close time. |
| Re-sync when Home Assistant starts | `none` (default), `open`, `close` |
| Start position | Optional, 0–100. Only used before any position has been saved. |
| Room code | Optional, must end in `-15` |

Reconfigure a blind: a menu with **Settings** (same form, entity kept) and **Measure open and close times**.

**Measure open and close times:** opens the blind fully, then sends close and times it until the user presses Submit when it stops, then sends open and times that the same way. Saves both times.

Delete a blind from its menu on the controller entry. Its entities and device go with it.

### Interface names that must match

These keep existing installs working. Treat them as fixed.

- Config entry `VERSION = 1`, `MINOR_VERSION = 3`. Unique ID: the controller ID, or the host when there's no ID.
- Controller entry data keys: `host`, `protocol` (`http`/`tcp`), `port`, `hub_id`.
- Controller options key: `room_names` (room code to name).
- Blind subentry type `blind`, title is the blind's name. Data keys: `blind_code`, `motor_code`, `rail`, `tdbu_extended`, `tilt`, `percent_support` (0/1/2), `close_time`, `open_time`, `startup_sync` (`none`/`open`/`close`), `start_position`, `parent_group` (room code).
- Blind subentry unique ID and blind cover entity unique ID: `neosmartblinds.<blind_code>.<motor_code>.<rail>`, for example `neosmartblinds.021.230-04.bf.1` (empty motor code gives `neosmartblinds.021.230-04..1`). Older versions used this, so existing entities, history and entity IDs carry over.
- Favourite button unique IDs: `<blind unique id>.favourite_1`, `<blind unique id>.favourite_2`.
- Room cover unique ID: `neosmartblinds.<room code>.room`.
- Connection sensor unique ID: `<controller device identifier>.connection`.
- Device identifiers: blind `(neosmartblinds, <blind unique id>)`, controller `(neosmartblinds, <entry unique id or entry id>)`, room `(neosmartblinds, neosmartblinds.<room code>.room)`.
- Action `neosmartblinds.send_command`.

## Entities

### Blind device

Each blind is a device linked through `via_device` to the controller. Model: the motor name from the table, or "Blind".

### Blind cover

- Assumed state (Home Assistant shows open and close buttons, no toggle).
- Open, close and stop always. Tilt open/close (micro-steps) only when **Supports tilt** is on.
- Set position only in modes 1 and 2.
- Rail and command set decide the actions (table under "Actions"). Tilt controls only appear when the rail has tilt actions.

**Mode 0, open and close only:** no position. Shows up, stop and down. Remembers whether it was last opened or closed, and restores that after a restart.

**Mode 1, blind moves to the position:** sends `01`–`99` (percent closed) and the blind goes there itself.

**Mode 2, timed position:** sends up or down, then sends stop after the time worked out from the open or close time and the distance.

**Both position modes:**

- Positions below 2 or above 98 send a plain close or open with no stop, which lets the motor reach its end stop and re-syncs the estimate.
- While moving, the estimated position updates every second, using the open time when rising and the close time when lowering.
- A new position requested mid-move: if the blind is already heading that way, extend or shorten the move without stopping. If the target is behind it, stop and then move back.
- Opening or closing fully counts as exact once the move time has passed.
- Save the position and restore it after a restart. Use **Start position** only when nothing has been saved. With neither, assume 50.

**Re-sync at startup:** if set to open or close, send that when Home Assistant starts (not on an integration reload).

### Favourite buttons

- **Favourite position 1** (`gp`) for every blind. **Favourite position 2** (`i2`) only for motor codes `no` and `rx`, or no motor code.
- Disabled by default, because the controller can't say whether a favourite has been saved.
- Pressing one doesn't change the estimated position.

### Room cover

- One for each room code shared by two or more blinds on a controller, unless the room code itself has been added as a blind.
- Its own device, named after the room. Cover name `<room name> Blinds`, for example *Frontyard Blinds*.
- Open, close, stop and set position go to every blind in the room at the same moment, so they get combined into one room command (see below) and each blind still tracks its own position.
- Position: average of the room's blinds. Offers a slider only if every blind uses mode 1 or 2.

### Combining commands into room commands

- When a blind with a room code gets a command, wait 250 ms.
- If every blind in that room got the same command within that window, send one command to the room code instead (channel 15), and update each blind's state as if it had been sent its own.
- Otherwise send each blind its own command after the wait.
- Blinds with no room code send straight away.

### Connection sensor

Binary sensor on the controller device, connectivity class, diagnostic category. On while the controller answers. Updated by every command, plus a check every 5 minutes that a TCP connection can be opened (no command sent).

## Notifications

Use Home Assistant persistent notifications.

- **Controller not answering:** one notice per controller. Clears itself when the controller answers again.
- **Command failed:** one notice per blind or room, naming the blind and the command, whether it came from the dashboard, an automation, a script or an action. Clears the next time a command to that blind or room is sent.
- A 401 doesn't add a notice (re-authentication covers it).

A failed command also raises a `HomeAssistantError` so the caller sees the error.

## Raw command action

`neosmartblinds.send_command`, target: covers from this integration. Field `command`, required, any two-character action. Sends `<blind code or room code>-<command>!<motor code>` to each target. Doesn't change estimated positions. The docs need a clear warning that programming commands can misconfigure a motor.

## Importing old YAML

Older versions were set up as:

```yaml
cover:
  - platform: neosmartblinds
    host: 192.168.1.20
    name: Front blind
    blind_code: "021.230-04"
    close_time: 20
    hub_id: <controller id>
    protocol: http
    port: 8838
    rail: 1
    percent_support: 0
    motor_code: bf
    start_position: 50      # optional
    parent_group: "021.230-15"  # optional
```

Defaults: `close_time` 20, `protocol` http, `port` 8838, `rail` 1, `percent_support` 0, `motor_code` empty. `protocol` may be any case.

On startup:

- Create one controller entry per controller (match on `hub_id`, or host when there's none) with a blind subentry per YAML entry. If the controller entry already exists, add missing blinds to it. Skip blinds that are already there.
- Imported blinds have **Supports tilt** off and re-sync `none`.
- Keep the existing entities (same unique ID, so same entity ID, history and customisations).
- Put the blind device in the area the old entity was in.
- Raise a repair issue asking the user to remove the YAML and restart.
- If an entry can't be imported (for example a bad blind code), raise a repair issue naming it and the reason.

## Diagnostics

Config entry diagnostics: blind settings, connection status and the last 20 commands with result. Remove host and controller ID.

## Docs

README covering: what you get, install (HACS and manual), setup with where to find each value in the Neo app, positioning modes, keeping the position accurate, room commands, the raw command action with its warning, upgrading from older versions, protocol reference, reporting a problem with diagnostics. No screenshots needed.

End the README with this section, word for word:

> ## Background and credits
>
> I originally used the integration by [@4n0nD3v3l0p3r](https://github.com/4n0nD3v3l0p3r/Home_Assistant_NeoSmartBlinds), and then the 2.x fork by [@mtgeekman](https://github.com/mtgeekman/Home_Assistant_NeoSmartBlinds), to control my blinds. Both were missing features I needed and hadn't been updated in years, so I rewrote the integration from scratch as version 4. It was written from a specification of how the integration should behave and Neo's published API documents, without reference to the earlier code, and none of the code from earlier versions was copied into it. Thanks to both of them, and to [@clara-j](https://github.com/clara-j) and [@gee-jay-bee](https://github.com/gee-jay-bee) for their work on the earlier versions.
>
> Version 4 is maintained by [@josh345rtfvqw](https://github.com/josh345rtfvqw).

## Tests and CI

- Pytest with `pytest-homeassistant-custom-component`, against a fake controller on localhost that speaks HTTP and TCP and records what it receives.
- Cover: the config flow (both steps, errors, duplicates, re-auth, reconfigure), blind subentry validation, each positioning mode's commands, mid-move changes, restore after restart, room command combining, YAML import (including unique IDs and repair issues), the raw command action, notifications.
- GitHub Actions: tests, hassfest and HACS validation on push, pull requests and weekly. A release workflow that tags and releases when the manifest version changes.

## Decisions

1. The domain stays `neosmartblinds`.
2. v2 YAML and v3.x installs upgrade in place, so the interface names above are kept exactly.
3. Favourite 1 sends `gp` for every motor.
4. The manifest version is `4.0.0`.
