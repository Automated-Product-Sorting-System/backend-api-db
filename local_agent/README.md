# Local Agent (Edge Gateway) 🏭

This component acts as a bi-directional bridge between the Cloud Infrastructure (Render API & MQTT Broker) and the Local Factory environment. It is a critical part of the Automated Sorting System's Data Pipeline.

## 📌 Architecture
Since the Cloud API cannot directly communicate with local factory networks due to NAT/Firewall restrictions, this Local Agent is deployed on a single machine connected to the same local network as the PLC. 

It operates with a **Stateful, Two-Way Architecture**:

1. **Downstream (Command Execution):** It subscribes to the Cloud MQTT Broker (`factory/plc/commands`), listens for control commands (`START`, `STOP`) sent from the UI, and translates them into **Modbus TCP** commands sent directly to the local PLC.
2. **Upstream (Telemetry & State Sync):** It runs a background thread that continuously polls the PLC's actual logical state via Modbus TCP every second. It then publishes this state to the cloud (`factory/plc/status`), allowing the cloud API to perform smart fault detection (e.g., detecting motor failures or manual overrides).

## ⚙️ Prerequisites
- This script must run on **ONLY ONE** machine (Laptop/Raspberry Pi) to avoid Hardware Collisions on the PLC.
- The machine must be physically or wirelessly connected to the same local network as the PLC.
- Python 3.8+ must be installed.

## 🚀 How to Setup & Run

### 1. Navigate to the local_agent directory:
    cd local_agent

### 2. Install dependencies:
    pip install -r requirements.txt

### 3. Configure Environment Variables:
Copy the .env.example file and rename it to .env, then fill in your actual Cloud MQTT credentials and the exact local IP address of the PLC.
    cp .env.example .env

### 4. Run the Agent:
    python local_agent.py

*Keep this terminal window running in the background during operations to maintain the bi-directional connection between the cloud and the machine.*