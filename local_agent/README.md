# Local Agent (Edge Gateway) 🏭

This component acts as a bi-directional bridge between the Cloud Infrastructure (Render API & MQTT Broker) and the Local Factory environment. It is a critical part of the Automated Sorting System's Data Pipeline, ensuring seamless integration between IT (Cloud) and OT (Hardware/PLC).

## 📌 Architecture
Since the Cloud API cannot directly communicate with local factory networks due to NAT/Firewall restrictions, this Local Agent is deployed on a single machine connected to the same local network as the PLC. 

It operates with a **Stateful, Two-Way Architecture (Closed-Loop)**:

1. **Downstream (Command Execution):** It subscribes to the Cloud MQTT Broker (`factory/plc/commands`) and listens for operational commands sent from the UI:
   - **START/STOP Commands:** Translates these commands into **Modbus TCP Coil 0** writes (Mapped to PLC physical output `Q0.0`) to physically start or halt the conveyor motor.
   - **Speed Control (`SET_SPEED`):** Receives a speed percentage (0-100%) from the UI, scales it mathematically to an 8-bit digital value (0-255), and pushes it to the PLC via **Modbus TCP Holding Register 10** (Mapped to PLC address `40011`).

2. **Upstream (Telemetry & State Sync):** It runs a background thread that continuously polls the PLC's actual logical state via Modbus TCP every second. It reads:
   - The motor logical status from **Coil 0**.
   - The currently registered speed from **Holding Register 10**.
   
   It then publishes both data points to the cloud (`factory/plc/status`), allowing the cloud API to compare the PLC target speed with the actual Speed Sensor telemetry to perform smart fault detection (e.g., detecting motor failures, belt jams, or manual overrides).

## ⚙️ Prerequisites
- This script must run on **ONLY ONE** machine to avoid Modbus Hardware Collisions on the PLC.
- The machine must be physically or wirelessly connected to the same local network as the PLC.
- Python 3.8+ must be installed.

## 🚀 How to Setup & Run

### 1. Navigate to the local_agent directory:
 ```bash
cd local_agent
```

### 2. Install dependencies:
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables:
Copy the `.env.example` file and rename it to `.env`, then fill in your actual Cloud MQTT credentials and the exact local IP address of the PLC.
```bash
cp .env.example .env
```

### 4. Run the Agent:
The execution command depends on your Operating System:

**For Ubuntu / Linux / macOS:**
```bash
python3 local_agent.py
```

**For Windows:**
```bash
python local_agent.py
```

*Keep this terminal window running in the background during operations to maintain the real-time, bi-directional connection between the cloud API and the factory machine.*