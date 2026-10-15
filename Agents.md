# Agent Definition - Frigate Face Tracking Bridge (waldo_cam)

## Description
A lightweight distributed IoT bridge service that watches Frigate NVR person detection events over MQTT, retrieves snapshot images, queries the `mlface` neural facial recognition service over WebSockets, and publishes identified person location events (name, camera, and room) back to the MQTT ecosystem.

## Role & Responsibilities
- **Frigate Event Monitor:** Subscribes to configured Frigate person detection topics (e.g., `<prefix>/<camera>/person`) across indoor and outdoor security cameras.
- **Snapshot Handler:** Captures snapshot JPEG frames when person activity is detected (`payload > 0`) via MQTT snapshot topics (`<prefix>/<camera>/person/snapshot`).
- **Facial Recognition Bridge:** Streams base64-encoded snapshot images over WebSockets to `mlface` (port 4785) and parses detected facial bounding boxes and known identity tags.
- **Location & Room Mapper:** Maps the detecting camera name to physical rooms/areas configured in a TOML settings file.
- **MQTT Event Dispatcher:** Publishes structured JSON identity alerts to a configured topic (e.g., `frig-fc/face-recog`). If a face is unrecognized, publishes with `"name": "unknown"`.
- **Throttling & Cooldown Manager:** Applies configurable debounce/cooldown timers per camera and identity to prevent flooding external facial recognition and MQTT brokers.

## Key Files
- [`waldo.py`](file:///home/ccoupe/Projects/iot/waldo_cam/waldo.py) - Main application entry point, integrating the asyncio event loop, MQTT client, WebSocket connection manager, and event pipeline.
- [`Settings.py`](file:///home/ccoupe/Projects/iot/waldo_cam/Settings.py) - Configuration parser supporting TOML files, parsing MQTT broker parameters, `mlface` endpoint details, camera-to-room mappings, and operational thresholds.
- [`Makefile`](file:///home/ccoupe/Projects/iot/waldo_cam/Makefile) - Build, local execution, virtual environment lifecycle, and system-level systemd deployment automation.
- [`waldo_cam.service`](file:///home/ccoupe/Projects/iot/waldo_cam/waldo_cam.service) - Systemd system service unit installed to `/etc/systemd/system/waldo_cam.service`.
- [`launch.sh`](file:///home/ccoupe/Projects/iot/waldo_cam/launch.sh) - Service wrapper script activating the python virtual environment and launching `waldo.py`.

## Integration Points
- **Subscribed MQTT Topics:**
  - `<prefix>/<camera>/person` (e.g. `frigate/mantle_cam/person` or `frig-fc/office_cam/person`) - Person count/state.
  - `<prefix>/<camera>/person/snapshot` - JPEG binary image payload associated with the detection.
- **Published MQTT Topics:**
  - `<publish_topic>` (e.g. `frig-fc/face-recog`) - JSON payload:
    ```json
    {
      "name": "cecil",
      "camera": "mantle_cam",
      "room": "kitchen",
      "timestamp": 1728864000.123
    }
    ```
- **External API Integrations:**
  - **mlface WebSocket Server:** `ws://<mlface_host>:<mlface_port>` (default port 4785) - bidirectional WebSocket protocol:
    - Request: base64-encoded JPEG binary string.
    - Response: JSON payload containing detected face matrices with bounding boxes, tag identities, and inference time.

## Context & Memory
- Caches recent snapshots in-memory per camera to pair with `person` activation events.
- Tracks detection cooldown timestamps per camera/person to avoid redundant `mlface` inference calls during continuous presence.
- Gracefully handles network and WebSocket reconnects to `mlface` and the MQTT broker using asynchronous tasks.
