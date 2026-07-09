# 🏭 NEXUS

### AI-Powered Industrial Inspection & Sorting Platform

![Python](https://img.shields.io/badge/Python-3.10-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![InfluxDB](https://img.shields.io/badge/InfluxDB_3.0-22ADF6?style=for-the-badge&logo=influxdb&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/sqlalchemy-%23D71F00.svg?style=for-the-badge&logo=sqlalchemy&logoColor=white)
![Polars](https://img.shields.io/badge/polars-0075ff?style=for-the-badge&logo=polars&logoColor=white)
![MQTT](https://img.shields.io/badge/MQTT-HiveMQ-660066?style=for-the-badge&logo=mqtt&logoColor=white)
![Cloudinary](https://img.shields.io/badge/Cloudinary-Asset_Management-3448C5?style=for-the-badge&logo=cloudinary&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

> **Connecting AI, Industrial IoT, Edge Computing, and Digital Manufacturing into a unified intelligent platform.**

An industrial-grade backend platform that powers an AI-driven product inspection and sorting system. The platform integrates Computer Vision, IoT sensors, PLC automation, Edge Computing, MQTT messaging, dual-database storage (PostgreSQL + InfluxDB), Cloudinary asset management, and real-time analytics through REST APIs and WebSockets.

---

## 🏗️ System Architecture & Data Flow

This backend is engineered to handle industrial-grade data flow, separating high-frequency time-series telemetry from relational business logic, while seamlessly bridging the physical factory floor with the cloud.

1. **Edge Layer (`local_agent`):** A lightweight daemon running on a local IPC/Raspberry Pi. It bridges Cloud MQTT with the physical PLC via **Modbus TCP**, executing commands and publishing machine state in real-time.
2. **Ingestion Layer:** A background MQTT subscriber (`mqtt_subscriber.py`) continuously listens to IoT sensors and streams data directly into InfluxDB.
3. **Storage Layer:**
   - **PostgreSQL:** Handles Users, Role-Based Access Control (RBAC), Sessions, and CV Inspection logs.
   - **InfluxDB:** Optimized for high-frequency sensor telemetry (Current, Speed, Temperature).
   - **Cloudinary:** Dynamic cloud storage for YOLO model inspection images, automatically categorizing assets based on status and defect types.
4. **Processing & API Layer:** **FastAPI** serves REST endpoints and WebSockets, utilizing **Polars** for lightning-fast time-series aggregation and state-block generation.

---

## ✨ Core Features & Analytics

* **🧠 Smart Correlation Engine:** Detects mechanical anomalies (e.g., motor jams, freewheeling, or calibration errors) by cross-referencing PLC commanded speed against actual physical belt speed (m/s) in real-time.
* **📊 AI Confidence Radar:** Aggregates and calculates the average confidence score of the YOLO Computer Vision model across all classification types (Good, Defected, Empty Bottle, etc.) to monitor AI health.
* **📈 Time-Series Aggregation & Timelines:** Uses **Polars** to compress thousands of raw telemetry data points into contiguous system state blocks (`RUNNING`, `STOPPED`, `OFFLINE`) for Machine Uptime analysis.
* **☁️ Dynamic Asset Management:** Integrates with Cloudinary API to dynamically move and categorize product images into respective defect folders upon human operator review.
* **🔐 Role-Based Access Control (RBAC):** Strict operational tiers (`Admin`, `Operator`, `Viewer`) securing machine control, user management, and session-based authentication.
* **⚡ Real-Time Telemetry:** Live sensor data streaming to mobile and web clients via secure **WebSockets**.

---

## 📂 Project Structure

```text
├── core/
│   └── utils.py                 # Cloudinary integration and helper functions
├── database_backups/
│   └── myDB.sql                 # PostgreSQL schema and initial seeds
├── databases/
│   ├── influx_conn.py           # InfluxDB 3.0 client and queries
│   ├── postgres_conn.py         # SQLAlchemy engine and session management
│   ├── models.py                # Relational ORM models (Users, Inspections, Sensors)
│   └── schemas.py               # Pydantic models for validation and serialization
├── local_agent/
│   ├── local_agent.py           # Edge MQTT-to-ModbusTCP bridge for PLC control
|   ├── .env.example             # Environment variables template
│   └── requirements.txt         # Edge-specific dependencies
├── .env.example                 # Environment variables template
├── docker-compose.yaml          # Infrastructure orchestration
├── Dockerfile                   # FastAPI containerization
├── main.py                      # FastAPI application, Routers, and Business Logic
├── mqtt_subscriber.py           # Background daemon for IoT telemetry ingestion
└── requirements.txt             # Cloud Backend dependencies
```

---

## 🚀 Setup & Installation

### 1. Prerequisites
* Docker & Docker Compose installed on your machine.
* *(Optional)* Python 3.10+ if running without Docker.

### 2. Clone the Repository
```bash
git clone https://github.com/Automated-Product-Sorting-System/backend-api-db.git
cd backend-api-db
```

### 3. Environment Variables
Create a `.env` file in the root directory and configure your credentials:
```bash
cp .env.example .env 
```
*Ensure you provide the connection strings for PostgreSQL, InfluxDB, Cloudinary, and your MQTT Broker.*

### 4. Run with Docker Compose
The easiest way to spin up the entire infrastructure (PostgreSQL, pgAdmin, InfluxDB, and the FastAPI app) is via Docker:
```bash
docker-compose up -d --build
```
The FastAPI application runs inside a Python 3.10-slim container, exposing port `8000`.

---

## 📖 API Documentation & Testing

Once the server is running, FastAPI automatically generates interactive OpenAPI documentation:

* **Swagger UI:** `http://localhost:8000/docs`
* **ReDoc:** `http://localhost:8000/redoc`

Use these interfaces to test analytical endpoints, authenticate users, and simulate Computer Vision uploads.

---

## 📡 WebSocket Telemetry Stream

Frontend and Mobile clients can connect to the live telemetry stream using secure WebSockets. 

**Endpoint:**
`wss://<YOUR_API_URL>/ws/telemetry?session_id=<USER_SESSION_ID>`

**Payload Format:**
```json
{
  "status": "success",
  "data": [
    {
      "sensor_id": "Speed_01",
      "speed_ms": 0.15,
      "speed_rpm": 120,
      "timestamp": "2026-07-10T14:30:00+00:00"
    },
    {
      "sensor_id": "PLC",
      "plc_status": "START",
      "speed_register": 128,
      "timestamp": "2026-07-10T14:30:01+00:00"
    }
  ]
}
```
*Note: The WebSocket will immediately drop the connection with Policy Violation Code `1008` if an invalid or expired session ID is provided.*

---
🎓 **Developed as part of the B.Sc. Graduation Project in Computer and Systems Engineering (Class of 2026).**