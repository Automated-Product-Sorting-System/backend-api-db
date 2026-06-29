# Automated Product Sorting System - Backend & Data Pipeline

A robust, high-performance backend API and data pipeline designed for an industrial Automated Product Sorting System. This system orchestrates IoT sensor telemetry, Computer Vision inspection results, and Machine (PLC) control using a dual-database architecture.

---

## 🏗️ System Architecture & Technologies

This backend is built to handle industrial-grade data flow, separating high-frequency time-series data from relational business logic.

* **Web Framework:** FastAPI (High performance, async support, auto-generated Swagger UI).
* **Relational Database:** PostgreSQL (Handles Users, RBAC, Sessions, and CV Inspection logs).
* **Time-Series Database:** InfluxDB (Optimized for high-frequency sensor telemetry).
* **IoT Messaging:** MQTT Protocol (For real-time PLC commands and sensor data ingestion).
* **Containerization:** Docker & Docker Compose.
* **Authentication:** JWT/Session-based with Bcrypt password hashing.

---

## ✨ Core Features

* **Role-Based Access Control (RBAC):** Strict operational tiers (`Admin`, `Operator`, `Viewer`) to secure machine control and user management.
* **Real-Time Telemetry:** Live sensor data streaming (Temperature, Current, Vibration) to mobile and web clients via **WebSockets**.
* **Automated Data Ingestion:** A background MQTT subscriber daemon (`mqtt_subscriber.py`) that continuously listens to factory sensors and writes directly to InfluxDB.
* **Computer Vision Integration:** Dedicated endpoints for the AI model to upload inspection results, classify defects, and store image paths.
* **Motor Control:** Secure REST endpoints for Operators/Admins to send `START` and `STOP` commands directly to the PLC via MQTT.

---

## 📂 Project Structure

* `core/`: Contains utility functions (e.g., image file management and dataset moving).
* `database_backups/`: Stores SQL dumps for PostgreSQL seeding and recovery.
* `databases/`: The core data layer containing ORM models, Pydantic schemas, and connection clients for both PostgreSQL and InfluxDB.
* `main.py`: The entry point for the FastAPI application holding all routing and business logic.
* `mqtt_subscriber.py`: Background worker script for MQTT data ingestion.
* `docker-compose.yaml` & `Dockerfile`: Infrastructure as Code (IaC) for seamless deployment.

---

## 🚀 Setup & Installation (Local Development)

Follow these steps to run the backend environment locally.

### 1. Prerequisites
* Docker & Docker Compose installed on your machine.
* Python 3.10+ (If running without Docker).

### 2. Clone the Repository
```bash
git clone https://github.com/Automated-Product-Sorting-System/backend-api-db.git
cd backend-api-db
```

### 3. Environment Variables
Create a `.env` file in the root directory based on the provided `.env.example`:
```bash
cp .env.example .env 
```

Ensure you fill in the required credentials for PostgreSQL, InfluxDB, and the MQTT Broker.

### 4. Run with Docker Compose
The easiest way to spin up the entire infrastructure is via Docker:
```bash
docker-compose up -d --build
```
This command will build the FastAPI image and start all interconnected services.

---

## 📖 API Documentation

Once the server is running, FastAPI automatically generates interactive API documentation. You can access it via:

* **Swagger UI:** `http://localhost:8000/docs`
* **ReDoc:** `http://localhost:8000/redoc`

Use these interfaces to test endpoints, authenticate users, and simulate Computer Vision uploads.

---

## 📡 WebSocket Connection Guide (Live Data)

Frontend and Mobile clients can connect to the live telemetry stream using secure WebSockets. 

**Endpoint:**
`wss://<YOUR_API_URL>/ws/telemetry?session_id=<USER_SESSION_ID>`

**Payload Format (Every 1 second):**
```json
{
  "status": "success",
  "data": [
    {
      "sensor_id": "Main_Motor_1",
      "timestamp": "2026-06-26T14:30:00Z",
      "temperature": 45.5,
      "current": 12.3,
      "vibration_x": 0.02,
      "vibration_y": 0.05,
      "vibration_z": 0.01
    }
  ]
}
```
*Note: The server returns policy violation code `1008` if an invalid or expired session ID is provided.*

---

## 🗺️ Roadmap & Upcoming Features

* **Analytical Endpoints:** Developing complex Flux and SQL queries to aggregate historical data (e.g., defect ratios, machine uptime).
* **Reporting Dashboards:** Exposing endpoints specifically tailored for plotting historical time-series charts on the frontend.