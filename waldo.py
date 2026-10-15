#!/usr/bin/env python3
"""
waldo_cam - Frigate Person Detection & Facial Recognition Bridge
Monitors Frigate MQTT person detection & snapshot topics, queries mlface via WebSockets,
and publishes identified person location events to MQTT.
"""

import argparse
import asyncio
import base64
import json
import logging
import logging.handlers
import os
import signal
import socket
import sys
import time
import urllib.request
import urllib.error
from typing import Optional

import paho.mqtt.client as mqtt
import websockets

from Settings import Settings


class WaldoBridge:
  def __init__(self, settings: Settings, log: logging.Logger):
    self.settings = settings
    self.log = log
    self.mqtt_client: Optional[mqtt.Client] = None
    self.msg_queue: asyncio.Queue = asyncio.Queue()
    self.loop: Optional[asyncio.AbstractEventLoop] = None

    # In-memory snapshot cache: cam_name -> (bytes, timestamp)
    self.snapshots: dict[str, tuple[bytes, float]] = {}
    # Synchronization events when waiting for a snapshot: cam_name -> asyncio.Event
    self.snapshot_events: dict[str, asyncio.Event] = {}
    # Last query time per camera for cooldown throttling: cam_name -> timestamp
    self.last_query: dict[str, float] = {}
    # Running state flag
    self.running = True

  def _init_mqtt(self):
    """Initializes and connects the Paho MQTT client."""
    client_id = self.settings.mqtt_client_name
    try:
      # Paho MQTT 2.0+ API
      self.mqtt_client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id, clean_session=True
      )
    except AttributeError:
      # Paho MQTT 1.x fallback
      self.mqtt_client = mqtt.Client(client_id, clean_session=True)

    if self.settings.mqtt_user and self.settings.mqtt_password:
      self.mqtt_client.username_pw_set(
        self.settings.mqtt_user, self.settings.mqtt_password
      )

    self.mqtt_client.on_connect = self._on_mqtt_connect
    self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
    self.mqtt_client.on_message = self._on_mqtt_message

    self.log.info(
      f"Connecting to MQTT broker at {self.settings.mqtt_server_ip}:{self.settings.mqtt_port}..."
    )
    self.mqtt_client.connect(
      self.settings.mqtt_server_ip, self.settings.mqtt_port, keepalive=60
    )
    self.mqtt_client.loop_start()

  def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
    if rc == 0:
      self.log.info(f"Connected to MQTT broker successfully (client_id: {client._client_id})")
      topics = self.settings.all_topics
      for topic in topics:
        rc_sub, _ = client.subscribe(topic, qos=1)
        if rc_sub == mqtt.MQTT_ERR_SUCCESS:
          self.log.debug(f"Subscribed to topic: {topic}")
        else:
          self.log.error(f"Failed to subscribe to topic {topic}: {rc_sub}")
      self.log.info(f"Subscribed to {len(topics)} Frigate camera topics.")
    else:
      self.log.error(f"MQTT connection failed with return code {rc}")

  def _on_mqtt_disconnect(self, client, userdata, flags, rc, properties=None):
    if rc != 0:
      self.log.warning(f"Unexpected MQTT disconnection (code {rc}). Paho will auto-reconnect.")
    else:
      self.log.info("Disconnected from MQTT broker.")

  def _on_mqtt_message(self, client, userdata, message):
    """Thread-safe MQTT message callback forwarding to asyncio event queue."""
    if not self.loop or self.loop.is_closed():
      return
    topic = message.topic
    payload = message.payload
    self.loop.call_soon_threadsafe(self.msg_queue.put_nowait, (topic, payload))

  def _fetch_http_snapshot(self, cam_name: str) -> Optional[bytes]:
    """Fetches high-resolution snapshot from Frigate HTTP API."""
    if not self.settings.frigate_url:
      return None
    urls = [
      f"{self.settings.frigate_url}/api/{cam_name}/person/snapshot.jpg",
      f"{self.settings.frigate_url}/api/{cam_name}/latest.jpg",
    ]
    for url in urls:
      try:
        req = urllib.request.Request(url, headers={"User-Agent": "waldo_cam/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
          if resp.status == 200:
            data = resp.read()
            if len(data) > 1000:
              return data
      except Exception as e:
        self.log.debug(f"[{cam_name}] HTTP snapshot fetch failed from {url}: {e}")
    return None

  async def query_mlface(self, image_bytes: bytes) -> Optional[dict]:
    """Sends JPEG image bytes over WebSocket to mlface and awaits recognition JSON."""
    uri = f"ws://{self.settings.mlface_host}:{self.settings.mlface_port}"
    try:
      b64_data = base64.b64encode(image_bytes).decode("ascii")
      async with websockets.connect(
        uri, close_timeout=self.settings.mlface_timeout
      ) as ws:
        await ws.send(b64_data)
        raw_reply = await asyncio.wait_for(
          ws.recv(), timeout=self.settings.mlface_timeout
        )
        return json.loads(raw_reply)
    except asyncio.TimeoutError:
      self.log.error(f"Timeout ({self.settings.mlface_timeout}s) querying mlface at {uri}")
    except ConnectionRefusedError:
      self.log.error(f"Connection refused connecting to mlface at {uri}")
    except Exception as e:
      self.log.error(f"Error querying mlface: {e}")
    return None

  async def process_person_detection(self, cam_name: str):
    """Asynchronous worker triggered when a person is detected on a camera."""
    cam_meta = self.settings.cameras.get(cam_name, {})
    if not cam_meta.get("enabled", True):
      return

    room = cam_meta.get("room", "unknown")
    cooldown = cam_meta.get("cooldown", self.settings.cooldown_seconds)

    # Cooldown check
    now = time.time()
    last_t = self.last_query.get(cam_name, 0.0)
    if now - last_t < cooldown:
      self.log.debug(
        f"[{cam_name}] In cooldown window ({now - last_t:.1f}s < {cooldown}s); skipping recognition."
      )
      return

    snapshot_bytes = None

    # 1. Attempt to fetch high-resolution snapshot from Frigate HTTP API if available
    if self.settings.frigate_url:
      try:
        snapshot_bytes = await self.loop.run_in_executor(
          None, self._fetch_http_snapshot, cam_name
        )
        if snapshot_bytes:
          self.log.debug(
            f"[{cam_name}] Retrieved high-res HTTP snapshot ({len(snapshot_bytes)} bytes)"
          )
      except Exception as e:
        self.log.debug(f"[{cam_name}] Error during HTTP snapshot fetch: {e}")

    # 2. Fall back to MQTT snapshot cache if HTTP fetch was not used or failed
    if snapshot_bytes is None:
      if cam_name in self.snapshots:
        snap_data, snap_time = self.snapshots[cam_name]
        if (now - snap_time) <= 2.5:
          snapshot_bytes = snap_data

      if snapshot_bytes is None:
        # Wait briefly for incoming MQTT snapshot
        if cam_name not in self.snapshot_events:
          self.snapshot_events[cam_name] = asyncio.Event()
        self.snapshot_events[cam_name].clear()

        try:
          await asyncio.wait_for(self.snapshot_events[cam_name].wait(), timeout=1.5)
          if cam_name in self.snapshots:
            snapshot_bytes, _ = self.snapshots[cam_name]
        except asyncio.TimeoutError:
          # Fall back to latest cached snapshot if available
          if cam_name in self.snapshots:
            snapshot_bytes, snap_time = self.snapshots[cam_name]
            self.log.debug(
              f"[{cam_name}] Snapshot wait timed out; falling back to cached snapshot from {now - snap_time:.1f}s ago."
            )

    if not snapshot_bytes:
      self.log.warning(f"[{cam_name}] No snapshot available for person detection.")
      return

    # Mark query timestamp before calling mlface to avoid duplicate in-flight queries
    self.last_query[cam_name] = time.time()
    self.log.info(f"[{cam_name}] Querying mlface for {room} ({len(snapshot_bytes)} bytes)...")

    reply = await self.query_mlface(snapshot_bytes)
    if not reply:
      return

    details = reply.get("details", {})
    matrices = details.get("matrices", [])
    infer_time = details.get("time", 0.0)

    # Extract detected tags/names
    detected_names = []
    for mat in matrices:
      tag = mat.get("tag")
      confidence = mat.get("confidence", 1.0)
      if tag and tag not in detected_names:
        detected_names.append((tag, confidence))

    if detected_names:
      for name, conf in detected_names:
        self.log.info(
          f"[{cam_name}] Recognized '{name}' in {room} (confidence: {conf:.2f}, inference: {infer_time:.2f}s)"
        )
        self.publish_recognition(name, cam_name, room, conf)
    elif self.settings.publish_unknown:
      self.log.info(
        f"[{cam_name}] Unrecognized face in {room} (inference: {infer_time:.2f}s); publishing 'unknown'"
      )
      self.publish_recognition("unknown", cam_name, room, 0.0)
    else:
      self.log.debug(f"[{cam_name}] No recognized faces in {room}; ignoring.")

  def publish_recognition(self, name: str, cam_name: str, room: str, confidence: float):
    """Publishes detection JSON payload to the configured MQTT topic."""
    payload = {
      "name": name,
      "camera": cam_name,
      "room": room,
      "confidence": round(confidence, 2),
      "timestamp": time.time(),
    }
    json_str = json.dumps(payload)
    self.mqtt_client.publish(self.settings.publish_topic, json_str, qos=1)
    self.log.info(f"MQTT Publish -> {self.settings.publish_topic}: {json_str}")

  async def run(self):
    """Main asynchronous message processing loop."""
    self.loop = asyncio.get_running_loop()
    self._init_mqtt()

    self.log.info("waldo_cam event loop started.")
    try:
      while self.running:
        topic, payload = await self.msg_queue.get()
        cam_info = self.settings.get_camera_info(topic)
        if not cam_info:
          self.log.debug(f"Ignoring message on unmapped topic: {topic}")
          self.msg_queue.task_done()
          continue

        cam_name, msg_type = cam_info

        if msg_type == "snapshot":
          self.snapshots[cam_name] = (payload, time.time())
          if cam_name in self.snapshot_events:
            self.snapshot_events[cam_name].set()
          self.log.debug(f"[{cam_name}] Snapshot updated ({len(payload)} bytes)")

        elif msg_type == "person":
          # Decode count/presence state
          payload_str = payload.decode("utf-8", errors="ignore").strip()
          try:
            count = int(float(payload_str))
          except ValueError:
            count = 1 if payload_str.lower() in ("on", "true", "active") else 0

          self.log.debug(f"[{cam_name}] Person status update: {count}")
          if count > 0:
            # Dispatch async task for non-blocking processing
            asyncio.create_task(self.process_person_detection(cam_name))

        self.msg_queue.task_done()
    except asyncio.CancelledError:
      self.log.info("Message queue task cancelled.")
    finally:
      self.stop()

  def stop(self):
    """Cleans up MQTT connections and tasks."""
    self.running = False
    if self.mqtt_client:
      self.mqtt_client.loop_stop()
      self.mqtt_client.disconnect()
      self.log.info("MQTT client stopped.")


def setup_logging(use_syslog: bool, debug: bool) -> logging.Logger:
  """Configures application logging for terminal or syslog."""
  log = logging.getLogger("waldo_cam")
  level = logging.DEBUG if debug else logging.INFO
  log.setLevel(level)

  # Clear existing handlers
  log.handlers.clear()

  if use_syslog:
    try:
      handler = logging.handlers.SysLogHandler(address="/dev/log")
      formatter = logging.Formatter("waldo_cam-%(levelname)-5s: %(message)s")
      handler.setFormatter(formatter)
      log.addHandler(handler)
    except Exception as e:
      print(f"Failed to initialize syslog handler ({e}); falling back to console.")
      handler = logging.StreamHandler(sys.stdout)
      formatter = logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
      )
      handler.setFormatter(formatter)
      log.addHandler(handler)
  else:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
      "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"
    )
    handler.setFormatter(formatter)
    log.addHandler(handler)

  return log


def test_mlface_oneshot(settings: Settings, log: logging.Logger, image_path: str):
  """CLI test helper: sends a local image to mlface and displays output."""
  if not os.path.isfile(image_path):
    log.error(f"Image file not found: {image_path}")
    sys.exit(1)

  with open(image_path, "rb") as f:
    img_data = f.read()

  log.info(f"Loaded {len(img_data)} bytes from {image_path}")
  bridge = WaldoBridge(settings, log)

  async def _test():
    res = await bridge.query_mlface(img_data)
    log.info(f"Response from mlface: {json.dumps(res, indent=2)}")

  asyncio.run(_test())


def test_camera_snapshot(settings: Settings, log: logging.Logger, cam_name: str):
  """CLI test helper: fetches snapshot for a camera and queries mlface."""
  bridge = WaldoBridge(settings, log)
  data = bridge._fetch_http_snapshot(cam_name)
  if not data:
    log.error(f"Could not fetch HTTP snapshot for camera '{cam_name}' from {settings.frigate_url}")
    sys.exit(1)

  log.info(f"Fetched {len(data)} bytes for {cam_name}")

  async def _test():
    res = await bridge.query_mlface(data)
    log.info(f"Response from mlface: {json.dumps(res, indent=2)}")

  asyncio.run(_test())


def main():
  hostname = socket.gethostname().split(".")[0]
  default_conf = f"{hostname}.toml"
  if not os.path.isfile(default_conf):
    default_conf = "waldo_cam.toml"

  parser = argparse.ArgumentParser(
    description="waldo_cam - Frigate Person Detection & Face Recognition Bridge"
  )
  parser.add_argument(
    "-c", "--conf", default=default_conf, type=str, help=f"Path to TOML configuration file (default: {default_conf})"
  )
  parser.add_argument(
    "-s", "--syslog", action="store_true", default=False, help="Log to system syslog instead of console"
  )
  parser.add_argument(
    "-d", "--debug", action="store_true", default=False, help="Enable verbose debug logging"
  )
  parser.add_argument(
    "--test-mlface", type=str, default=None, metavar="IMAGE_PATH", help="Send a test JPEG to mlface and exit"
  )
  parser.add_argument(
    "--test-cam", type=str, default=None, metavar="CAMERA_NAME", help="Fetch camera snapshot from Frigate HTTP API and query mlface"
  )

  args = parser.parse_args()

  log = setup_logging(args.syslog, args.debug)
  log.info(f"Starting waldo_cam on {hostname}...")

  if not os.path.isfile(args.conf):
    log.error(f"Configuration file not found: {args.conf}")
    sys.exit(1)

  settings = Settings(args.conf, log)
  if args.debug:
    settings.log_level = "DEBUG"
    log.setLevel(logging.DEBUG)

  settings.print()

  if args.test_mlface:
    test_mlface_oneshot(settings, log, args.test_mlface)
    sys.exit(0)

  if args.test_cam:
    test_camera_snapshot(settings, log, args.test_cam)
    sys.exit(0)

  bridge = WaldoBridge(settings, log)

  def _sig_handler(sig, frame):
    log.info("Shutdown signal received.")
    bridge.running = False
    sys.exit(0)

  signal.signal(signal.SIGINT, _sig_handler)
  signal.signal(signal.SIGTERM, _sig_handler)

  try:
    asyncio.run(bridge.run())
  except KeyboardInterrupt:
    log.info("Keyboard interrupt received. Exiting.")


if __name__ == "__main__":
  main()
