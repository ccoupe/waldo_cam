# waldo_cam

**waldo_cam** is an MQTT-based bridge for home IoT automation. It monitors Frigate NVR person detection events, grabs camera snapshot images, runs facial recognition against an [`mlface`](file:///home/ccoupe/Projects/iot/mlface/mlface.py) WebSocket service, maps the detecting camera to a physical room, and publishes identified person location events back to MQTT.

```
┌─────────────────┐       MQTT (person > 0 & snapshot)       ┌───────────────┐
│   Frigate NVR   │ ───────────────────────────────────────> │   waldo_cam   │
└─────────────────┘                                          └──┬─────────┬──┘
                                                                │         │
                     WebSocket: Base64 JPEG                     │         │ MQTT: JSON
                                │                               │         │ {"name":...,
                                v                               │         │  "camera":...,
                         ┌─────────────┐                        │         │  "room":...}
                         │   mlface    │ <──────────────────────┘         │
                         │ (Face Rec.) │ ───────────────────────┐         v
                         └─────────────┘  WebSocket: Matched Tag│   ┌───────────────┐
                                                                └──>│ Home Displays │
                                                                    │ & Automation  │
                                                                    └───────────────┘
```

## Features

- **Asynchronous Event-Driven Architecture:** Uses Python's `asyncio` combined with `paho-mqtt` and `websockets` to handle event notifications, snapshot streaming, and recognition without blocking.
- **Configurable TOML Settings:** Simple configuration via a TOML file (e.g. `nopi.toml`, `pi5.toml`, or `config.toml`) managed through a dedicated [`Settings`](file:///home/ccoupe/Projects/iot/waldo_cam/Settings.py) class.
- **Dynamic Camera-to-Room Mapping:** Maps any camera name to physical rooms/zones.
- **Debounce & Cooldown Throttling:** Avoids repetitive queries to `mlface` when people linger in a camera's field of view.
- **Dual Logging Support:** Interactive colorized console logging for testing and development, or standard syslog logging for daemonized background operation.
- **Deployment via Makefile & Systemd:** Follows the established IoT project convention with `make install`, `make update`, `make start`, and `make stop`.

## Documentation

- [Agent Definition](Agents.md): Detailed agent role, integration points, subscribed topics, and published payloads.
- [Architecture & Event Flow](ARCHITECTURE.md): Deep dive into the asyncio loop integration, MQTT message dispatching, and `mlface` protocol.
- [Settings Configuration](Settings.md): Full schema of the TOML configuration file with options and defaults.

## Quick Start

### 1. Prerequisites

Install [`uv`](https://docs.astral.sh/uv/) for Python package management:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Setup & Virtual Environment

Initialize the environment and install dependencies:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 3. Local Testing

Run `waldo_cam` directly in your terminal with live console logging:

```bash
python3 waldo.py -c config.toml
```

To run with verbose debug output:

```bash
python3 waldo.py -c config.toml -d
```

### 4. System Installation

Install and register as a system-level systemd service (does not require a user login session):

```bash
sudo make install
sudo make start
```

Check service status or logs:

```bash
sudo systemctl status waldo_cam.service
sudo journalctl -u waldo_cam.service -f
```
