# Neo Smart Blinds for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Default-41BDF5)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/josh345rtfvqw/ha-neosmartblinds?label=Release)](https://github.com/josh345rtfvqw/ha-neosmartblinds/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-yellow)](https://github.com/josh345rtfvqw/ha-neosmartblinds/blob/master/LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.8%2B-blue)](https://www.home-assistant.io)
![Connection](https://img.shields.io/badge/Connection-Local-brightgreen)
[![Validate](https://github.com/josh345rtfvqw/ha-neosmartblinds/actions/workflows/validate.yml/badge.svg)](https://github.com/josh345rtfvqw/ha-neosmartblinds/actions/workflows/validate.yml)

Control blinds through a Neo Smart Controller on your local network. No cloud, no extra Python packages. Everything is set up from the Home Assistant UI.

The controller never reports where a blind is, so Home Assistant works out the position from the commands it sends and the times you give it. This README explains how to keep that estimate accurate.

## What you get

- **A controller device** for each Neo Smart Controller, with a **Connection** sensor (diagnostic) that's on while the controller answers.
- **A blind device and cover** for each blind you add. Open, close and stop always. Optional tilt (micro-step) buttons. Optional position slider.
- **Favourite position buttons** for each blind: Favourite position 1 for every blind, and Favourite position 2 for NEO (`no`) and Raex (`rx`) motors or blinds with no motor code. They're disabled by default because the controller can't tell Home Assistant whether a favourite has been saved. Enable them on the blind's device page if you use them.
- **A room device and cover** for each room code shared by two or more blinds, so you can move the whole room at once.
- **Room commands**: when every blind in a room gets the same command at the same time, one room command goes out instead of one per blind.
- **The `neosmartblinds.send_command` action** for sending any two-character command.
- **Notifications** when the controller stops answering or a command fails.
- **Diagnostics** for reporting problems.

## Install

### HACS

1. Open HACS in Home Assistant.
2. Search for **Neo Smart Blinds** and download it. If it doesn't show up, add `https://github.com/josh345rtfvqw/ha-neosmartblinds` as a custom repository (type: Integration) first.
3. Restart Home Assistant.

### Manual

1. Download the latest release from the [releases page](https://github.com/josh345rtfvqw/ha-neosmartblinds/releases).
2. Copy `custom_components/neosmartblinds` into the `custom_components` folder in your Home Assistant config folder, so you end up with `config/custom_components/neosmartblinds/manifest.json`.
3. Restart Home Assistant.

Home Assistant 2025.8 or newer is needed.

## Setup

### Add the controller

Go to **Settings > Devices & services > Add integration > Neo Smart Blinds**.

1. **Host** and **Protocol**. HTTP is recommended because the controller reports errors over HTTP. Over TCP it echoes back whatever it gets, so a wrong command or blind code fails silently.
2. **Port** (filled in as 8838 for HTTP or 8839 for TCP) and **Controller ID** (needed for HTTP, not used for TCP).

Home Assistant checks it can open a connection to the controller. It doesn't send a command. The entry is called `Neo Smart Controller (<host>)`.

To change the host, protocol, port or ID later, open the controller entry's menu and choose **Reconfigure**. If the controller ever answers that the controller ID wasn't found (HTTP 401), Home Assistant asks you for the ID again.

### Add blinds

On the controller entry, choose **Add blind**. One entry is one rail of one blind code.

| Field | What to enter |
|---|---|
| Name | What to call the blind. |
| Blind code | `ID1.ID2-channel`, for example `021.230-04`. ID1 and ID2 are 000 to 255. Channel `01` to `14` is one blind, `15` is the whole room. |
| Motor code | Pick the motor brand from the list, or type any two-character code. Leave it empty if your blind doesn't use one. |
| Rail | 1 top/middle (default), 2 bottom, 3 both. Rails 2 and 3 are for top-down/bottom-up blinds. |
| Extended top-down/bottom-up commands | Off by default. Uses the `u4`/`d4`/`x2` command set. Only for motor codes `mb`, `ra`, `ap` and `db` when the motor is the top-down/bottom-up type. |
| Supports tilt | Adds tilt open and close, which send micro-steps. Only works on rails that have micro-step commands (rail 1 and rail 2 with the standard set). |
| Positioning mode | See [Positioning modes](#positioning-modes). |
| Close time | Seconds from fully open to fully closed. Default 20. |
| Open time | Seconds from fully closed to fully open. Leave empty to use the close time. |
| Re-sync when Home Assistant starts | None (default), open or close. See [Keeping the position accurate](#keeping-the-position-accurate). |
| Start position | 0 to 100. Only used before any position has been saved. |
| Room code | Optional. The blind's room code, ending in `-15`, for example `021.230-15`. |

To change a blind later, open its menu on the controller entry and choose **Reconfigure**. **Settings** opens the same form (the entity, its history and its entity ID stay the same). **Measure open and close times** times the blind for you. To remove a blind, choose **Delete** from the same menu. Its entities and device go with it.

To name rooms, choose **Configure** on the controller entry. There's one field per room code shared by two or more blinds. Rooms you don't name are called `Room <room code>`, and the room cover is called `<room name> Blinds`.

### Where to find each value in the Neo app

- **Host**: the controller's IP address is under **Your Controllers**. If you have more than one controller, use the one the blind's room is assigned to. Giving the controller a fixed IP address in your router is a good idea.
- **Controller ID**: the 24-character ID is shown under **Your Controller**.
- **Blind code**: open the blind and go to its advanced page. It shows the ID pair (ID1.ID2) and the channel. Every blind in a room shares the same ID pair.
- **Room code**: the room's ID pair with channel `15`. For blinds `021.230-04` and `021.230-05`, the room code is `021.230-15`.
- **Motor code**: not shown in the app. Pick the brand of your motor. The codes come from Neo's motor table:

| Code | Motor | | Code | Motor |
|---|---|---|---|---|
| `bf` | Bofu (standard) | | `wt` | Wistar / Alpha |
| `vb` | Bofu (vertical) | | `db` | Dooya (bi-directional) |
| `tb` | Bofu top-down/bottom-up | | `sy` | Somfy RTS |
| `no` | NEO | | `gp` | Gaposa |
| `rx` | Raex | | `ra` | Rollease ARC |
| `nc` | Nice F-Code | | `re` | Rollease EL |
| `nr` | Nice 0-Code | | `ap` | AMP (Turnils) |
| `k1` | A-OK (standard) | | `sf` | Sunfrere |
| `k2` | A-OK v2 (Louvolite) | | `rc` | Ronco |
| `k3` | A-OK v3 (Eclipse) | | `bl` | Alta Bliss |
| `dy` | Dooya (unidirectional) | | `mb` | Coulisse MotionBlinds |
| `by` | Bofu/Dooya (deprecated) | | `jo` | Jiecang |

## Positioning modes

**0, Open and close only.** No position slider. The cover shows open, stop and close, and remembers whether it was last opened or closed, including after a restart.

**1, Blind moves to the position.** Home Assistant sends a position and the motor goes there by itself. Neo's commands use percent **closed**, so 30% open in Home Assistant is sent as `70`. Only for the top rail, without the extended commands, and with a motor code that accepts positions (`no`, `db`, `ra`, `rb`, `ap`, `bl`, `mb`, `jo`) or no motor code.

**2, Timed position (estimated).** Works with any motor. Home Assistant sends open or close, then sends stop once the blind should have reached the position. The time comes from the open or close time and how far it has to go.

In both position modes:

- Asking for less than 2% sends a plain close and more than 98% sends a plain open, with no stop. The motor runs to its end stop, which puts the estimate back in sync.
- While a blind moves, its position updates every second, using the open time when rising and the close time when lowering.
- If you pick a new position while it's moving and the blind is already heading that way, the move is extended or shortened without stopping. If the new position is behind it, the blind stops and then moves back.
- The position is saved and restored after a restart. The start position is only used when nothing has been saved. With neither, Home Assistant assumes 50%.

## Keeping the position accurate

The controller never reports where a blind is, so the position is an estimate. A few things keep it close:

- **Measure the times.** Use **Reconfigure > Measure open and close times** on the blind. Home Assistant opens the blind fully, then closes it and times it until you press Submit when it stops, then opens it and times that the same way. Both times are saved.
- **Run to the ends now and then.** A full open or close (or any position under 2% or over 98%) runs the motor to its end stop and counts as exact once the move time has passed.
- **Re-sync at startup.** Set **Re-sync when Home Assistant starts** to open or close and the blind is sent there whenever Home Assistant starts. It isn't sent when the integration reloads.
- **Use the cover.** If you move a blind with the remote or the Neo app, Home Assistant doesn't know. Open or close it from Home Assistant to get back in sync.
- **Favourites don't move the estimate.** Pressing a favourite button leaves the estimated position where it was, because Home Assistant doesn't know where the favourite is.

## Room commands

Blinds that share a room code (set in **Room code**) get a room cover. Open, close, stop and set position on the room cover go to every blind in the room at the same moment.

When a blind with a room code gets a command, Home Assistant waits 250 ms. If every blind in that room got the same command in that time, one command goes to the room code (channel 15) instead, and each blind still tracks its own position as if it had been sent its own command. If not, each blind gets its own command after the wait. Blinds with no room code send straight away.

This also works when an automation or scene moves every blind in a room at once.

Things to know:

- A room command moves every blind the controller has in that room, including any you haven't added to Home Assistant.
- Blinds with different motor codes can't share a room command, so they get their own.
- The room cover's position is the average of its blinds. It has a position slider only if every blind in the room uses mode 1 or 2.
- There's no room cover if you've added the room code itself as a blind.

## Raw command action

`neosmartblinds.send_command` sends any two-character command to the selected blind or room covers. Each target gets `<blind code or room code>-<command>!<motor code>`. It doesn't change any estimated positions.

```yaml
action: neosmartblinds.send_command
target:
  entity_id: cover.front_blind
data:
  command: i1
```

This is how you reach commands the cover doesn't use, such as `i1` (intermediate position 1 on NEO motors) and `op`/`cl` on top-down/bottom-up blinds.

> **Warning:** some commands are for programming the motor. Sending one by mistake can misconfigure a motor, and fixing that may need the remote or the blind's installer. Only send commands you understand, and check Neo's documents first.

## Upgrading from older versions

Version 2 (YAML) and 3.x installs upgrade in place. Entities keep their unique IDs, so entity IDs, history, names and customisations carry over.

If you still have YAML like this:

```yaml
cover:
  - platform: neosmartblinds
    host: 192.168.1.20
    name: Front blind
    blind_code: "021.230-04"
    close_time: 20
    hub_id: <24 character id>
    protocol: http
    port: 8838
    rail: 1
    percent_support: 0
    motor_code: bf
```

it's imported when Home Assistant starts:

- One controller entry per controller (matched on `hub_id`, or the host when there's no ID), with a blind for each YAML entry. If the controller is already set up, missing blinds are added to it and existing ones are skipped.
- Imported blinds have **Supports tilt** off and re-sync set to none.
- The blind's device goes in the area the old entity was in.
- A repair issue asks you to remove the YAML and restart. Once it's gone, the blinds stay set up in the UI.
- If an entry can't be imported (for example a bad blind code), a repair issue names it and says why. Fix the YAML and restart, or add the blind from the UI.

## Protocol reference

From Neo's API documents (version 1.8, July 2025): the [Local HTTP API](https://help.neosmartblinds.com/portal/api/kbArticles/414972000003758017/locale/en/attachments/8ygk312bbd60298b54311bfd0964e865c998f/content?portalId=edbsnc3f14403ccf379185be762f5beac126c0f74fc067d682dc474506fed7073ca55&inline=true) and the [Basic Open TCP API](https://help.neosmartblinds.com/portal/api/kbArticles/414972000003758017/locale/en/attachments/8ygk38d91fef701534c6e88561cbbeee3186b/content?portalId=edbsnc3f14403ccf379185be762f5beac126c0f74fc067d682dc474506fed7073ca55&inline=true). The documents don't publish redistribution terms, so they're linked here rather than copied into this repo.

Commands look like `ID1.ID2-CHANNEL-ACTION!MOTORCODE`, for example `021.230-04-up!bf`. `!MOTORCODE` is left off when there's no motor code.

**HTTP (port 8838):** `GET http://<host>:8838/neo/v1/transmit?command=<command>&id=<controller id>&hash=<hash>`. The hash is 7 digits and never reused (the last 7 digits of the time in milliseconds, plus 1 if it matches the last one). Responses: 200 sent, 400 invalid command, 401 controller ID not found, 404 wrong path, 409 hash already used (retried once with a new hash). 10 second timeout.

**TCP (port 8839):** open a connection, send the command plus CRLF, read the echo, close. The controller echoes whatever it gets before checking it, so TCP can't report a bad command. 10 second timeout.

**Pacing:** the controller handles one command at a time and takes at least 500 ms per command. Commands to each controller are queued and sent at least 0.7 s apart. The connection sensor is updated by every command, plus a check every 5 minutes that only opens a TCP connection.

| Action | Meaning |
|---|---|
| `up`, `dn`, `sp` | Open, close, stop (top rail) |
| `mu`, `md` | Micro-step up/down (tilt), top rail |
| `01` to `99` | Go to a position, in percent closed |
| `gp` | Favourite position 1 |
| `i2` | Favourite position 2 |
| `u2`, `d2`, `o2`, `c2` | Bottom rail: open, close, micro-step up, micro-step down |
| `u3`, `d3` | Both rails: open, close |
| `u4`, `d4`, `x2` | Extended set: middle rail open, close, stop |
| `op`, `cl` | Top-down/bottom-up: open shades, close shades (raw command only) |
| `i1` | Intermediate position 1, NEO motors (raw command only) |

Which actions each blind uses:

| Rail | Standard set | Extended set |
|---|---|---|
| 1 top/middle | `up` `dn` `sp`, tilt `mu` `md` | `u4` `d4` `x2`, no tilt |
| 2 bottom | `u2` `d2` `sp`, tilt `o2` `c2` | `u2` `d2` `x2`, no tilt |
| 3 both | `u3` `d3` `sp`, no tilt | `u3` `d3` `x2`, no tilt |

## Reporting a problem

1. Go to **Settings > Devices & services > Neo Smart Blinds**, open the controller entry's menu and choose **Download diagnostics**. The file has your blind settings, the connection status and the last 20 commands with their results. The host and controller ID are removed.
2. If you can, turn on debug logging for the integration (**Enable debug logging** in the same menu), repeat the problem, then turn it off to download the log.
3. [Open an issue](https://github.com/josh345rtfvqw/ha-neosmartblinds/issues) with the diagnostics file, the log and what you expected to happen.

## Background and credits

I originally used the integration by [@4n0nD3v3l0p3r](https://github.com/4n0nD3v3l0p3r/Home_Assistant_NeoSmartBlinds), and then the 2.x fork by [@mtgeekman](https://github.com/mtgeekman/Home_Assistant_NeoSmartBlinds), to control my blinds. Both were missing features I needed and hadn't been updated in years, so I rewrote the integration from scratch. It was written from a specification of how the integration should behave and Neo's published API documents, without reference to the earlier code, and none of the code from earlier versions was copied into it. Thanks to both of them, and to [@clara-j](https://github.com/clara-j) and [@gee-jay-bee](https://github.com/gee-jay-bee) for their work on the earlier versions.

Version 4 is maintained by [@josh345rtfvqw](https://github.com/josh345rtfvqw).
