import os
import json
import time
import threading
import logging
import paho.mqtt.client as mqtt
from datetime import datetime, timezone
from paho.mqtt.enums import CallbackAPIVersion
from pymodbus.client import ModbusTcpClient
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


# Cloud MQTT Config
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
COMMAND_TOPIC = "factory/plc/commands"         # Topic used to send commands to the PLC
STATUS_TOPIC = "factory/plc/status"          # Topic used to publish the PLC status


# Local PLC Config
PLC_IP = os.getenv("PLC_IP")
PLC_PORT = int(os.getenv("PLC_PORT", 502))


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        logger.info("Connected to Cloud MQTT Broker!")
        logger.info(f"Listening for commands on topic: {COMMAND_TOPIC}")
        client.subscribe(COMMAND_TOPIC)
    else:
        logger.error(f"Failed to connect to MQTT Broker, return code {rc}")

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    if reason_code == 0:
        logger.info("Disconnected gracefully from Cloud MQTT Broker.")
    else:
        logger.warning(
            f"Unexpectedly disconnected from Cloud MQTT Broker. Reason code: {reason_code}"
        )

start_stop_coil_address = 0  # Maps to start/stop coil in the PLC
speed_register_address = 10  # Maps to speed register in the PLC

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        command = payload.get("command")
       
        if not command:
            return
            
        logger.info(f"\nReceived command from cloud API: {command}")
        logger.info("Forwarding command to local PLC via Modbus TCP...")
       
        plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
        try:
            if not plc_client.connect():
                logger.error("Error: Could not connect to local PLC. Check IP and network connection!")
                return
        
            # Start/Stop motor
            if command == "START":
                plc_client.write_coil(start_stop_coil_address, True)
                logger.info("PLC Status: MOTOR STARTED")
           
            elif command == "STOP":
                plc_client.write_coil(start_stop_coil_address, False)
                logger.info("PLC Status: MOTOR STOPPED")
            
            # Set Belt Speed
            elif command == "SET_SPEED":
                speed_percentage = payload.get("value", 0)
            
                # Convert percentage (0-100) to digital value (0-255)
                plc_value = int((speed_percentage / 100.0) * 255)
            
                # Write the value to the Holding Register 
                plc_client.write_register(speed_register_address, plc_value)
            
                logger.info(f"PLC Status: SPEED SET TO {speed_percentage}% (Register Value: {plc_value})")
            
        finally:
            plc_client.close()
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")


def publish_plc_status(mqtt_client):
    """
    Background function that periodically reads the motor status and speed from the PLC and publishes it to the cloud.
    """
    while True:
        try:
            plc_client = ModbusTcpClient(PLC_IP, port=PLC_PORT)
            try:
                if plc_client.connect():
                    # Read Coil (which controls the motor)
                    coil_result = plc_client.read_coils(start_stop_coil_address, 1)
                
                    # Read Holding Register (speed register)
                    reg_result = plc_client.read_holding_registers(speed_register_address, 1)
                
                    if not coil_result.isError() and not reg_result.isError():
                        is_running = coil_result.bits[0]
                        status_str = "START" if is_running else "STOP"
                        speed_val = reg_result.registers[0] # Get the 8-bit value (0-255)
                   
                        # Prepare and publish payload
                        payload = json.dumps({
                            "status": status_str, 
                            "speed_register": speed_val,
                            "timestamp": datetime.now(timezone.utc).isoformat(), 
                            "source": "local_agent"})
                        
                        mqtt_client.publish(STATUS_TOPIC, payload)
            finally:
                plc_client.close()
                
        except Exception as e:
            logger.error(f"Error reading PLC status: {e}")
       
        time.sleep(3)  # Read every 3 second


# Initialize MQTT Client
client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
if MQTT_USERNAME and MQTT_PASSWORD:
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

if MQTT_PORT == 8883:
    client.tls_set()

client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message

# Automatic reconnect with exponential backoff
client.reconnect_delay_set(min_delay=1, max_delay=30)

logger.info("Starting Edge Local Agent for Automated Sorting System...")

try:
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
   
    # Run PLC status monitor in a separate thread to avoid blocking command reception
    status_thread = threading.Thread(
        target=publish_plc_status, 
        args=(client,), 
        daemon=True
    )
    status_thread.start()
    logger.info("PLC Status Monitor running in background...")
   
    client.loop_forever()

except KeyboardInterrupt:
    logger.info("\nLocal Agent stopped by user.")
except Exception as e:
    logger.error(f"Connection Error: {e}")