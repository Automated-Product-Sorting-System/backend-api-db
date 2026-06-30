import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from influxdb_client.client.influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS, WriteOptions

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "")

if not INFLUXDB_TOKEN or not INFLUXDB_URL:
    raise ValueError("InfluxDB configuration is missing in .env file!")

client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = client.write_api(write_options=SYNCHRONOUS)
batch_options = WriteOptions(batch_size=50, flush_interval=1000, jitter_interval=200, retry_interval=5000, max_retries=3)
batch_write_api = client.write_api(write_options=batch_options)
query_api = client.query_api()

def get_latest_telemetry():
    """
    Fetches the latest sensor readings from InfluxDB and dynamically aggregates them into a single dictionary per sensor_id.
    """
    query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
        |> range(start: -1h)
        |> filter(fn: (r) => r._measurement == "SensorData")
        |> last()
    '''
    tables = query_api.query(query)
    
    # Dictionary to group all sensor readings under their respective sensor_id
    sensors_dict = {}
    
    for table in tables:
        for record in table.records:
            s_id = record.values.get("sensor_id")
            
            # If this is the first field read for this sensor_id, initialize its dictionary
            if s_id not in sensors_dict:
                sensors_dict[s_id] = {
                    "sensor_id": s_id,
                    "timestamp": record.get_time().isoformat()
                }
            
            # Extract the field name (temperature, current, vibration_x, ...) and its value
            field_name = record.get_field()
            field_value = record.get_value()
            
            # Add the field to the dictionary associated with the same sensor_id
            sensors_dict[s_id][field_name] = field_value
            
    # Return the values as a list of dictionaries for the WebSocket JSON
    return list(sensors_dict.values())

def get_telemetry_for_day(date_str: str):
    """
    Fetches raw 'current' and 'plc_status' telemetry for a specific date (YYYY-MM-DD).
    Returns a flat list of dictionaries optimized for Polars DataFrame ingestion.
    """
    # Convert the date string to start and end datetime objects for the day
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # The Query to fetch current and PLC status readings for the day
    query = f'''
        from(bucket: "{INFLUXDB_BUCKET}")
        |> range(start: {start_iso}, stop: {end_iso})
        |> filter(fn: (r) => r._measurement == "SensorData")
        |> filter(fn: (r) => r._field == "plc_status" or r._field == "current")
        |> keep(columns: ["_time", "_field", "_value"])
    '''
    
    tables = query_api.query(query)
    
    raw_data = []
    # Convert the returned tables to a flat list of dictionaries
    for table in tables:
        for record in table.records:
            raw_data.append({
                "time": record.get_time(),
                "field": record.get_field(),
                "value": record.get_value()
            })
            
    return raw_data