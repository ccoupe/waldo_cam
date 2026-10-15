import asyncio
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from Settings import Settings
from waldo import WaldoBridge


class TestSettings(unittest.TestCase):
  def setUp(self):
    self.log = logging.getLogger("test_settings")
    self.log.setLevel(logging.CRITICAL)

  def test_load_nopi_toml(self):
    toml_path = os.path.join(os.path.dirname(__file__), "nopi.toml")
    st = Settings(toml_path, self.log)

    self.assertIn(st.mqtt_server_ip, ("bronco", "bronco.local"))
    self.assertEqual(st.mqtt_port, 1883)
    self.assertEqual(st.publish_topic, "homie/face-recog")
    self.assertEqual(st.mlface_host, "bigboy")
    self.assertEqual(st.mlface_port, 4785)
    self.assertIn(st.frigate_url, ("http://bronco:5000", "http://bronco.local:5000"))
    self.assertTrue(st.publish_unknown)

    # Active cameras
    self.assertIn("office_cam", st.cameras)
    self.assertEqual(st.cameras["office_cam"]["room"], "Office")
    self.assertEqual(st.cameras["office_cam"]["person_topic"], "frig-fc/office_cam/person")
    self.assertEqual(
      st.cameras["office_cam"]["snapshot_topic"], "frig-fc/office_cam/person/snapshot"
    )

    # Reverse lookup map: since frigate_url is configured in nopi.toml,
    # MQTT snapshot topics are omitted from subscriptions
    cam, m_type = st.get_camera_info("frig-fc/office_cam/person")
    self.assertEqual(cam, "office_cam")
    self.assertEqual(m_type, "person")

    self.assertIsNone(st.get_camera_info("frig-fc/office_cam/person/snapshot"))

  def test_disabled_camera(self):
    test_toml = """
[mqtt]
server_ip = "127.0.0.1"

[cameras]
cam1 = { room = "Kitchen", prefix = "frigate", enabled = true }
cam2 = { room = "Garage", prefix = "frigate", enabled = false }
"""
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as tf:
      tf.write(test_toml)
      tf_name = tf.name

    try:
      st = Settings(tf_name, self.log)
      self.assertIn("cam1", st.cameras)
      self.assertNotIn("cam2", st.cameras)
      self.assertIsNotNone(st.get_camera_info("frigate/cam1/person"))
      self.assertIsNone(st.get_camera_info("frigate/cam2/person"))
      # When frigate_url is unset, snapshot topic IS registered for enabled cameras
      self.assertIsNotNone(st.get_camera_info("frigate/cam1/person/snapshot"))
    finally:
      os.unlink(tf_name)


class TestWaldoBridge(unittest.IsolatedAsyncioTestCase):
  def setUp(self):
    self.log = logging.getLogger("test_bridge")
    self.log.setLevel(logging.CRITICAL)
    toml_path = os.path.join(os.path.dirname(__file__), "nopi.toml")
    self.settings = Settings(toml_path, self.log)
    self.settings.cooldown_seconds = 0.0  # disable cooldown for testing
    self.settings.frigate_url = None      # test with MQTT snapshot fallback
    self.bridge = WaldoBridge(self.settings, self.log)
    self.bridge.mqtt_client = MagicMock()

  async def test_process_known_face(self):
    # Prepare dummy snapshot
    self.bridge.snapshots["office_cam"] = (b"fake_jpeg_bytes", 1000.0)

    # Mock mlface response with known face "cecil"
    mlface_reply = {
      "details": {
        "plug": "face",
        "matrices": [
          {"tag": "cecil", "confidence": 0.98, "x": 10, "y": 20, "width": 50, "height": 50}
        ],
        "time": 0.12,
      }
    }

    with patch.object(self.bridge, "query_mlface", new_callable=AsyncMock) as mock_ml:
      mock_ml.return_value = mlface_reply

      await self.bridge.process_person_detection("office_cam")

      # Verify mqtt_client.publish was called
      self.bridge.mqtt_client.publish.assert_called_once()
      call_args = self.bridge.mqtt_client.publish.call_args[0]
      topic = call_args[0]
      payload = json.loads(call_args[1])

      self.assertEqual(topic, "homie/face-recog")
      self.assertEqual(payload["name"], "cecil")
      self.assertEqual(payload["camera"], "office_cam")
      self.assertEqual(payload["room"], "Office")
      self.assertEqual(payload["confidence"], 0.98)

  async def test_process_unknown_face(self):
    # Prepare dummy snapshot
    self.bridge.snapshots["office_cam"] = (b"fake_jpeg_bytes", 1000.0)

    # Mock mlface response with no matched tag (unknown face)
    mlface_reply = {
      "details": {
        "plug": "face",
        "matrices": [],
        "time": 0.08,
      }
    }

    with patch.object(self.bridge, "query_mlface", new_callable=AsyncMock) as mock_ml:
      mock_ml.return_value = mlface_reply

      await self.bridge.process_person_detection("office_cam")

      self.bridge.mqtt_client.publish.assert_called_once()
      call_args = self.bridge.mqtt_client.publish.call_args[0]
      topic = call_args[0]
      payload = json.loads(call_args[1])

      self.assertEqual(topic, "homie/face-recog")
      self.assertEqual(payload["name"], "unknown")
      self.assertEqual(payload["camera"], "office_cam")
      self.assertEqual(payload["room"], "Office")
      self.assertEqual(payload["confidence"], 0.0)


if __name__ == "__main__":
  unittest.main()
