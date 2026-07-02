import os
import polars as pl
from dotenv import load_dotenv
from datetime import datetime, timedelta
from influxdb_client_v3 import InfluxDBClient3

load_dotenv()

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "")

if not INFLUXDB_TOKEN or not INFLUXDB_URL:
    raise ValueError("InfluxDB configuration is missing in .env file!")

influx_client = InfluxDBClient3(
    host=INFLUXDB_URL,
    token=INFLUXDB_TOKEN,
    org=INFLUXDB_ORG,
    database=INFLUXDB_BUCKET
)

def get_latest_telemetry():
    """
    Fetches the latest sensor readings from InfluxDB and dynamically aggregates them into a single dictionary per sensor_id.
    """
    query = """
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY "sensor_id" ORDER BY "time" DESC) as rn
            FROM "SensorData"
            WHERE "time" >= now() - INTERVAL '1 hour'
        ) WHERE rn = 1
    """
    
    table = influx_client.query(query=query, language="sql")
    data = table.to_pylist()
    
    for row in data:
        if "time" in row:
            row["timestamp"] = row.pop("time").isoformat()
        if "rn" in row:
            del row["rn"]
            
    return data

def get_telemetry_for_day(date_str: str):
    """
    Fetches raw 'current' and 'plc_status' telemetry for a specific date (YYYY-MM-DD).
    Returns a flat list of dictionaries optimized for Polars DataFrame ingestion.
    """
    # Convert the date string to start and end datetime objects for the day
    start_dt = datetime.strptime(date_str, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    
    # Convert to ISO format for SQL query
    start_iso = start_dt.strftime("%Y-%m-%d 00:00:00")
    end_iso = end_dt.strftime("%Y-%m-%d 00:00:00")
    
    # Current sensor readings only
    current_query = f"""
        SELECT time, current
        FROM "SensorData"
        WHERE time >= '{start_iso}' AND time < '{end_iso}'
          AND sensor_id = 'Curr_01'
          AND current IS NOT NULL
        ORDER BY time ASC
    """
    
    # PLC status readings only
    plc_query = f"""
        SELECT time, plc_status
        FROM "SensorData"
        WHERE time >= '{start_iso}' AND time < '{end_iso}'
          AND sensor_id = 'PLC'
          AND plc_status IS NOT NULL
        ORDER BY time ASC
    """
    
    current_table = influx_client.query(query=current_query, language="sql")
    plc_table = influx_client.query(query=plc_query, language="sql")

    current_rows = current_table.to_pylist()
    plc_rows = plc_table.to_pylist()

    if not current_rows:
        return []

    current_df = pl.DataFrame(current_rows).sort("time")

    if not plc_rows:
        # No PLC status recorded that day; still return current readings
        return current_df.with_columns(pl.lit(None).alias("plc_status")).to_dicts()

    plc_df = pl.DataFrame(plc_rows).sort("time")

    # As-of backward join: for each 'current' timestamp, attach the last known 'plc_status' at or before that moment
    merged_df = current_df.join_asof(plc_df, on="time", strategy="backward")

    return merged_df.to_dicts()