# Settings Documentation

This document describes the configuration options supported by [`Settings.py`](file:///home/ccoupe/Projects/iot/waldo_cam/Settings.py) for the `waldo_cam` service. Settings are configured using a standard TOML file (e.g. `<hostname>.toml` or `config.toml`).

## Example Configuration (`config.toml` / `nopi.toml`)

```toml
[mqtt]
server_ip = "bronco.local"
port = 1883
client_name = "nopi_waldo"
publish_topic = "homie/face-recog"

[mlface]
host = "bigboy"
port = 4785
timeout = 10.0

[frigate]
# Direct Frigate HTTP API endpoint for high-resolution snapshots.
# Recommended: avoids Frigate's 270x270 MQTT downscaled compression.
url = "http://bronco.local:5000"

[general]
cooldown_seconds = 10.0   # Default min seconds between mlface queries for same camera
publish_unknown = true     # Publish alert even if face is unrecognized ("unknown")
log_level = "INFO"        # DEBUG, INFO, WARNING, ERROR

# List of cameras to monitor and their room mappings
[cameras]
trumpy_cam   = { room = "Family Room", prefix = "frig-fc" }
pi5_cam      = { room = "Office",  prefix = "frig-fc" }
doorbell_cam = { room = "Front Entry", prefix = "frig-fc" }
office_cam   = { room = "Office",  prefix = "frig-fc" }
living_cam   = { room = "Family Room", prefix = "frig-fc" }
# Disable noisy cameras or cameras without snapshots:
garage_cam   = { room = "Garage",  prefix = "frig-fc", enabled = false }
# Or adjust camera-specific cooldown:
# patio_cam  = { room = "Patio", prefix = "frig-fc", cooldown = 60.0 }
```

## Settings Reference

### 1. `[mqtt]` Section

Configures the MQTT client connection to the central broker.

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `server_ip` | string | `"bronco.local"` | Hostname or IP address of the MQTT broker. |
| `port` | integer | `1883` | TCP port for the MQTT broker. |
| `client_name` | string | `"<node>_waldo"` | Client ID used when connecting to the MQTT broker. |
| `user` | string | `""` | Optional MQTT username. |
| `password` | string | `""` | Optional MQTT password. |
| `publish_topic` | string | `"frig-fc/face-recog"` | Topic where recognition events are published as JSON. |

### 2. `[mlface]` Section

Configures the connection to the `mlface` WebSocket facial recognition service.

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `host` | string | `"192.168.1.2"` | IP address or hostname running the `mlface.py` WebSocket server. |
| `port` | integer | `4785` | WebSocket port where `mlface` listens. |
| `timeout` | float | `10.0` | Maximum seconds to wait for a face recognition response before timing out. |

### 3. `[frigate]` Section (Recommended)

Configures direct HTTP API snapshot retrieval from Frigate NVR.

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `url` | string | `None` | URL to Frigate NVR (e.g. `http://bronco.local:5000`). When configured, `waldo_cam` fetches full-resolution snapshots directly via `/api/<camera>/person/snapshot.jpg` instead of relying on the low-resolution (270x270) MQTT snapshot stream. |

### 4. `[general]` Section

Configures operational behavior, throttling, and logging.

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `cooldown_seconds` | float | `10.0` | Default debounce window per camera in seconds. |
| `publish_unknown` | boolean | `true` | If `true`, publishes an MQTT message even if `mlface` detects a face but cannot match a known name. |
| `log_level` | string | `"INFO"` | Default logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

### 5. `[cameras]` Section

Defines the cameras monitored by `waldo_cam` and pairs each camera to a physical room location and topic prefix.

Each camera entry supports the following properties:

| Key | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `room` | string | `"unknown"` | Room/location name published in identity event payloads. |
| `prefix` | string | `"frigate"` | MQTT topic prefix used by Frigate (e.g. `frigate` or `frig-fc`). |
| `enabled` | boolean | `true` | Set to `false` to ignore noisy or unneeded cameras completely. |
| `cooldown` | float | `cooldown_seconds` | Override cooldown period (in seconds) for this specific camera. |
| `person_topic` | string | `<prefix>/<cam>/person` | Custom override for person detection topic. |
| `snapshot_topic` | string | `<prefix>/<cam>/person/snapshot` | Custom override for snapshot topic. |
