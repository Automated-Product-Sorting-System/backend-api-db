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
MQTT_TOPIC = "factory/sensors"          # Sensors data topic
STATUS_TOPIC = "factory/plc/status"               # PLC status topic

if not MQTT_BROKER or not MQTT_TOPIC:
    raise ValueError("MQTT_BROKER or MQTT_TOPIC is missing in the .env file!")


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info(f"Connected to MQTT Broker at {MQTT_BROKER}:{MQTT_PORT}")
        # Subscribe to both sensors topic and PLC status topic
        client.subscribe([(MQTT_TOPIC, 0), (STATUS_TOPIC, 0)])
        logger.info(f"Successfully subscribed to topics: {MQTT_TOPIC} and {STATUS_TOPIC}")
    else:
        logger.error(f"Connection failed with return code: {rc}")


def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode("utf-8"))

        # Message from PLC
        if topic == STATUS_TOPIC:
            plc_status = payload.get("status", "UNKNOWN")
            speed_register = payload.get("speed_register", 0)
            
            # S
            point = Point("SensorData").tag("sensor_id", "PLC")
            point.field("plc_status", plc_status)
            point.field("speed_register", int(speed_register))
            
            batch_write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            logger.info(f"PLC status persisted: {plc_status} | Speed Reg: {speed_register}")
            return 

        # Message from ESP
        if topic == MQTT_TOPIC:
            if isinstance(payload, list):
                for item in payload:
                    sensor_id = item.get("sensor_id")
                    timestamp = item.get("timestamp")
                    
                    if not sensor_id:
                        continue 

                    point = Point("SensorData").tag("sensor_id", sensor_id)
                    
                    if timestamp:
                        point.time(timestamp)
                    
                    has_fields = False
                    
                    # Process each field in the item
                    for field, value in item.items():
                        if field in ["sensor_id", "timestamp"]:
                            continue
                        point.field(field, float(value))
                        has_fields = True
                        
                    if has_fields:
                        batch_write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
                
                logger.info("Batch of independent sensor readings processed.")
            else:
                logger.warning("Received payload is not a JSON Array. Please check the IoT device format.")

    except json.JSONDecodeError:
        logger.error("Failed to decode incoming MQTT message payload.")
    except Exception as e:
        logger.error(f"Error during InfluxDB ingestion pipeline: {str(e)}")


def main():
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
   
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
   
    if MQTT_PORT == 8883:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    try:
        logger.info(f"Initializing connection to MQTT Broker...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("MQTT Subscriber service stopped by administrator.")
    except Exception as e:
        logger.critical(f"MQTT Service crashed unexpectedly: {str(e)}")
    finally:
        logger.info("Flushing remaining InfluxDB batch writes...")
        batch_write_api.close()


if __name__ == "__main__":
    main()