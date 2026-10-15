import os
import socket
import logging
from typing import Optional

try:
  import tomllib
except ModuleNotFoundError:
  import tomli as tomllib


class Settings:
  """Settings loader and configuration manager for waldo_cam."""

  def __init__(self, config_file: str, log: logging.Logger = None):
    self.config_file = config_file
    self.log = log or logging.getLogger("waldo_cam")
    self.hostname = socket.gethostname().split(".")[0]

    # MQTT Settings
    self.mqtt_server_ip = "bronco.local"
    self.mqtt_port = 1883
    self.mqtt_client_name = f"{self.hostname}_waldo"
    self.mqtt_user = None
    self.mqtt_password = None
    self.publish_topic = "frig-fc/face-recog"

    # MLFace Settings
    self.mlface_host = "192.168.1.2"
    self.mlface_port = 4785
    self.mlface_timeout = 10.0

    # Frigate HTTP API Settings (for high-resolution snapshots)
    self.frigate_url: Optional[str] = None

    # General Settings
    self.cooldown_seconds = 10.0
    self.publish_unknown = True
    self.log_level = "INFO"

    # Cameras mapping: camera_name -> {room, prefix, person_topic, snapshot_topic, cooldown, enabled}
    self.cameras = {}
    # Reverse lookup: topic -> (camera_name, "person" | "snapshot")
    self.topic_map = {}

    self.load_toml(self.config_file)

  def load_toml(self, filepath: str):
    if not os.path.isfile(filepath):
      raise FileNotFoundError(f"Configuration file not found: {filepath}")

    with open(filepath, "rb") as f:
      conf = tomllib.load(f)

    # [mqtt]
    mqtt_conf = conf.get("mqtt", {})
    self.mqtt_server_ip = mqtt_conf.get(
      "server_ip", mqtt_conf.get("mqtt_server_ip", self.mqtt_server_ip)
    )
    self.mqtt_port = int(
      mqtt_conf.get("port", mqtt_conf.get("mqtt_port", self.mqtt_port))
    )
    self.mqtt_client_name = mqtt_conf.get(
      "client_name", mqtt_conf.get("mqtt_client_name", self.mqtt_client_name)
    )
    self.mqtt_user = mqtt_conf.get("user", mqtt_conf.get("mqtt_user", None))
    self.mqtt_password = mqtt_conf.get("password", mqtt_conf.get("mqtt_password", None))
    self.publish_topic = mqtt_conf.get(
      "publish_topic", mqtt_conf.get("recog_topic", self.publish_topic)
    )

    # [mlface]
    mlface_conf = conf.get("mlface", {})
    self.mlface_host = mlface_conf.get("host", self.mlface_host)
    self.mlface_port = int(mlface_conf.get("port", self.mlface_port))
    self.mlface_timeout = float(mlface_conf.get("timeout", self.mlface_timeout))

    # [frigate]
    frig_conf = conf.get("frigate", {})
    self.frigate_url = frig_conf.get(
      "url", conf.get("general", {}).get("frigate_url", self.frigate_url)
    )
    if self.frigate_url:
      self.frigate_url = self.frigate_url.rstrip("/")

    # [general]
    gen_conf = conf.get("general", {})
    self.cooldown_seconds = float(gen_conf.get("cooldown_seconds", self.cooldown_seconds))
    self.publish_unknown = bool(gen_conf.get("publish_unknown", self.publish_unknown))
    self.log_level = gen_conf.get("log_level", self.log_level).upper()

    # [cameras]
    cam_conf = conf.get("cameras", {})
    self.cameras.clear()
    self.topic_map.clear()

    for cam_name, info in cam_conf.items():
      enabled = True
      cooldown = self.cooldown_seconds
      if isinstance(info, str):
        # Allow shorthand: cam_name = "room"
        room = info
        prefix = "frigate"
        person_top = f"{prefix}/{cam_name}/person"
        snap_top = f"{prefix}/{cam_name}/person/snapshot"
      elif isinstance(info, dict):
        enabled = info.get("enabled", True)
        if not enabled:
          self.log.info(f"Camera '{cam_name}' is disabled; skipping.")
          continue
        room = info.get("room", "unknown")
        prefix = info.get("prefix", "frigate")
        cooldown = float(info.get("cooldown", self.cooldown_seconds))
        person_top = info.get("person_topic", f"{prefix}/{cam_name}/person")
        snap_top = info.get("snapshot_topic", f"{prefix}/{cam_name}/person/snapshot")
      else:
        continue

      self.cameras[cam_name] = {
        "room": room,
        "prefix": prefix,
        "person_topic": person_top,
        "snapshot_topic": snap_top,
        "cooldown": cooldown,
        "enabled": enabled,
      }
      self.topic_map[person_top] = (cam_name, "person")
      if not self.frigate_url:
        self.topic_map[snap_top] = (cam_name, "snapshot")

    self.log.info(f"Loaded {len(self.cameras)} active cameras from {filepath}")

  @property
  def all_topics(self) -> list[str]:
    """Returns all MQTT topics that waldo_cam needs to subscribe to."""
    return list(self.topic_map.keys())

  def get_camera_info(self, topic: str):
    """Returns (cam_name, 'person' | 'snapshot') for a subscribed topic, or None."""
    return self.topic_map.get(topic)

  def print(self):
    """Outputs current configuration to log."""
    self.log.info("=== Waldo Cam Settings ===")
    self.log.info(f" Config File    : {self.config_file}")
    self.log.info(f" MQTT Broker    : {self.mqtt_server_ip}:{self.mqtt_port}")
    self.log.info(f" MQTT Client    : {self.mqtt_client_name}")
    self.log.info(f" Publish Topic  : {self.publish_topic}")
    self.log.info(f" MLFace Server  : {self.mlface_host}:{self.mlface_port}")
    self.log.info(f" MLFace Timeout : {self.mlface_timeout}s")
    self.log.info(f" Frigate API URL: {self.frigate_url or 'None (using MQTT snapshots)'}")
    self.log.info(f" Default Cooldown: {self.cooldown_seconds}s")
    self.log.info(f" Publish Unknown: {self.publish_unknown}")
    self.log.info(f" Active Cameras : {len(self.cameras)}")
    for cam, meta in self.cameras.items():
      self.log.info(
        f"   - {cam:<12} -> Room: {meta['room']} (Prefix: {meta['prefix']}, Cooldown: {meta['cooldown']}s)"
      )
    self.log.info("==========================")
