import os
import json
import logging
from datetime import datetime
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from dotenv import load_dotenv
import ssl
from influxdb_client.client.write.point import Point

# Internal imports
from databases.influx_conn import batch_write_api, INFLUXDB_BUCKET, INFLUXDB_ORG

# Configure logging for production environment
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
MQTT_BROKER = os.getenv("MQTT_BROKER", "")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "")

if not MQTT_BROKER or not MQTT_TOPIC:
    raise ValueError("MQTT_BROKER or MQTT_TOPIC is missing in the .env file!")

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
        # Expected payload format: {"sensor_id": "SN-001", "timestamp": "2026-01-01T00:00:00Z", "temperature": 24.5, ...}
        payload = json.loads(msg.payload.decode("utf-8"))
        sensor_id = payload.get("sensor_id")
        timestamp = payload.get("timestamp")
        if not sensor_id:
            logger.warning("Received payload missing 'sensor_id' field. Skipping write.")
            return

        # Create the Point outside the loop, passing sensor_id as a tag
        point = Point("SensorData").tag("sensor_id", sensor_id)
        
        # Set the timestamp if provided
        if timestamp:
            point.time(timestamp)
        
        has_fields = False
        
        #  Iterate through fields and add them to the same Point to ensure exact same Timestamp
        for field, value in payload.items():
            if field in ["sensor_id", "timestamp"]:
                continue
            
            point.field(field, float(value))
            has_fields = True
            
        # # Execute the database write operation via the Background Batcher
        if has_fields:
            batch_write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            logger.info(f"Telemetry metrics processed and persisted for sensor: {sensor_id}")

    except json.JSONDecodeError:
        logger.error("Failed to decode incoming MQTT message payload. Ensure payload is valid JSON.")
    except ValueError as ve:
        logger.error(f"Data type error (e.g., cannot convert value to float): {str(ve)}")
    except Exception as e:
        logger.error(f"Error during InfluxDB ingestion pipeline: {str(e)}")

def main():
    # Instantiate client using Paho MQTT v2 API standards
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    
    # Enable TLS for port 8883 (HiveMQ Cloud)
    if MQTT_PORT == 8883:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    try:
        logger.info(f"Initializing connection to MQTT Broker...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        
        # Blocking loop to maintain network traffic and process automatic reconnects
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("MQTT Subscriber service stopped by administrator.")
    except Exception as e:
        logger.critical(f"MQTT Service crashed unexpectedly: {str(e)}")
    finally:
        # Flush any remaining batched writes before closing
        logger.info("Flushing remaining InfluxDB batch writes...")
        batch_write_api.close()    

if __name__ == "__main__":
    main()