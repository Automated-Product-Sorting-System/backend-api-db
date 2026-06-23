import os
import json
import logging
from datetime import datetime
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from dotenv import load_dotenv
from influxdb_client import Point

# Internal imports
from databases.influx_conn import write_api, INFLUXDB_BUCKET, INFLUXDB_ORG

# Configure logging for production environment
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC")

def on_connect(client, userdata, flags, rc, properties=None):
    """
    Callback executed when the client receives a CONNACK response from the broker.
    """
    if rc == 0:
        logger.info(f"Connected to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC)
        logger.info(f"Successfully subscribed to topic: {MQTT_TOPIC}")
    else:
        logger.error(f"Connection failed with return code: {rc}")

def on_message(client, userdata, msg):
    """
    Callback executed when a MQTT message is received from the broker.
    Handles data transformation and writes directly to InfluxDB.
    """
    try:
        # Expected payload format: {"sensor_id": "SN-001", "temperature": 24.5, "pressure": 1.2}
        payload = json.loads(msg.payload.decode("utf-8"))
        sensor_id = payload.get("sensor_id")
        
        if not sensor_id:
            logger.warning("Received payload missing 'sensor_id' field. Skipping write.")
            return

        # Iterate through fields dynamically to construct the Time-Series Point
        for field, value in payload.items():
            if field == "sensor_id":
                continue
            
            # Construct InfluxDB Point aligned with your influx_conn.py mapping
            point = Point("SensorData") \
                .tag("sensor_id", sensor_id) \
                .field(field, float(value)) \
                .time(datetime.utcnow())
            
            # Synchronous write to the specified bucket
            write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            
        logger.info(f"Telemetry metrics processed and persisted for sensor: {sensor_id}")

    except json.JSONDecodeError:
        logger.error("Failed to decode incoming MQTT message payload. Ensure payload is valid JSON.")
    except Exception as e:
        logger.error(f"Error during InfluxDB ingestion pipeline: {str(e)}")

def main():
    # Instantiate client using Paho MQTT v2 API standards
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        logger.info(f"Initializing connection to MQTT Broker...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        
        # Blocking loop to maintain network traffic and process automatic reconnects
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("MQTT Subscriber service stopped by administrator.")
    except Exception as e:
        logger.critical(f"MQTT Service crashed unexpectedly: {str(e)}")

if __name__ == "__main__":
    main()