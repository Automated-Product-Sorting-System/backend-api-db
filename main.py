from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect, Query, status, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from uuid import UUID
from typing import Optional
from passlib.context import CryptContext
import paho.mqtt.publish as publish
import json
import os
import threading
import uvicorn
import asyncio
import uuid
import shutil

# Internal imports
from core.utils import move_to_confirmed_dataset, delete_inspection_image
from databases import models
from databases import schemas
from databases.postgres_conn import engine, get_db, SessionLocal
from databases.influx_conn import get_latest_telemetry
import mqtt_subscriber

# ==========================================
# Lifespan (Startup & Shutdown Events)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Cloud Services...")
    # Create PostgreSQL tables based on models.py
    models.Base.metadata.create_all(bind=engine)
    print("Database Tables Verified.")
    
    # Start mqtt_subscriber in a background thread
    mqtt_thread = threading.Thread(target=mqtt_subscriber.main, daemon=True)
    mqtt_thread.start()
    print("MQTT Subscriber is running in the background.")
    
    yield # Server is running 
    
    print("Shutting down Cloud Services...")

# ==========================================
# FastAPI Setup
# ==========================================
app = FastAPI(title="Automated Sorting System API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static files directory
app.mount("/static", StaticFiles(directory="."), name="static")

# ==========================================
# Password Hashing Setup
# ==========================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if the provided plain password matches the hashed one."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Generate a hashed version of the plain password."""
    return pwd_context.hash(password)

# ==========================================
# Session Dependency
# ==========================================

def get_current_session(
    x_session_id: UUID = Header(..., description="The Session ID obtained from login"), 
    db: Session = Depends(get_db)
):
    """
    It checks the header sent from the frontend and compares it to the session table in PostgreSQL
    """
    session = db.query(models.SystemSession).filter(
        models.SystemSession.session_id == x_session_id,
        models.SystemSession.expires_at > datetime.now()
    ).first()
    
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session. Please login again.")
    
    return session

# ==========================================
# Authentication & User Management Endpoints
# ==========================================

@app.get("/")
def home():
    return {"status": "Online"}

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    # Find the user by username
    user = db.query(models.User).filter(
        models.User.username == request.username
    ).first()
    
    # Verify user exists and the password matches the hash
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password")
    
    # Define session expiration (e.g., 8 hours)
    expiration_time = datetime.now() + timedelta(hours=8)
    
    # Create a new session
    new_session = models.SystemSession(
        user_id=user.user_id, 
        expires_at=expiration_time)
    
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    return {
        "message": "Login successful",
        "session_id": new_session.session_id,
        "user_id": user.user_id, 
        "username": user.username, 
        "role": user.user_role
    }

@app.post("/create-user")
def create_user(request: schemas.UserCreate, db: Session = Depends(get_db)):
    # Hash the password before saving it to the database
    hashed_password = get_password_hash(request.password)
    
    users_count = db.query(models.User).count()
    
    if users_count == 0:
        assigned_role = schemas.UserRole.Admin  # First user is always an admin
    else:
        assigned_role = schemas.UserRole.Viewer  # Subsequent users are viewers
    
    new_user = models.User(
        username=request.username,
        password_hash=hashed_password,  # Store the hashed password
        user_role=assigned_role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"message": "User created successfully", "user_id": new_user.user_id}

@app.post("/logout")
def logout(
    current_session: models.SystemSession = Depends(get_current_session), 
    db: Session = Depends(get_db)
):
    # Expire the current session
    current_session.expires_at = datetime.now()
    db.commit()
    
    return {"message": "Logged out successfully"}

# ==========================================
# Admin-Specific User Creation Endpoint
# ==========================================

class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    user_role: schemas.UserRole  # Admin, Operator, or Viewer

@app.post("/admin/create-user")
def admin_create_user(
    request: AdminCreateUserRequest, 
    current_session: models.SystemSession = Depends(get_current_session), 
    db: Session = Depends(get_db)
):
    # Verify only admins can create users
    current_admin = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    
    if not current_admin or current_admin.user_role != schemas.UserRole.Admin:
        raise HTTPException(status_code=403, detail="Only Admin can create users with specific roles")

    # Check if the username is already taken
    existing_user = db.query(models.User).filter(models.User.username == request.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Hash the password before saving it to the database
    hashed_password = get_password_hash(request.password)
    
    # Create the new user with the specified role
    new_user = models.User(
        username=request.username,
        password_hash=hashed_password,
        user_role=request.user_role
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {
        "message": f"User '{request.username}' created successfully as {request.user_role.value}", 
        "user_id": new_user.user_id,
        "assigned_role": request.user_role.value
    }

# ==========================================
# User Edit Endpoints
# ==========================================

class EditPasswordRequest(BaseModel):
    new_password: str

class EditUsernameRequest(BaseModel):
    new_username: str

class EditRoleRequest(BaseModel):
    new_role: schemas.UserRole  # (Admin, Operator or Viewer)

@app.put("/edit-password/{user_id}")
def edit_password(
    user_id: int, 
    request: EditPasswordRequest, 
    current_session: models.SystemSession = Depends(get_current_session), 
    db: Session = Depends(get_db)
):
    # Verify current user
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    
    # Ensure user is editing their own account or is an Admin
    if current_session.user_id != user_id and current_user.user_role != schemas.UserRole.Admin:
        raise HTTPException(status_code=403, detail="You can only edit your own account")

    # Find the target user to edit
    user_to_edit = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user_to_edit:
        raise HTTPException(status_code=404, detail="User not found")

    # Hash the new password before updating
    hashed_new_password = get_password_hash(request.new_password)
    user_to_edit.password_hash = hashed_new_password
    
    db.commit()

    return {"message": "Password updated successfully"}

@app.put("/edit-username/{user_id}")
def edit_username(
    user_id: int, 
    request: EditUsernameRequest, 
    current_session: models.SystemSession = Depends(get_current_session), 
    db: Session = Depends(get_db)
):
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    
    if current_session.user_id != user_id and current_user.user_role != schemas.UserRole.Admin:
        raise HTTPException(status_code=403, detail="You can only edit your own account")

    user_to_edit = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user_to_edit:
        raise HTTPException(status_code=404, detail="User not found")

    # Confirm the new username is not already taken
    existing_user = db.query(models.User).filter(
        models.User.username == request.new_username,
        models.User.user_id != user_id
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already exists")

    user_to_edit.username = request.new_username
    db.commit()

    return {"message": "Username updated successfully"}

@app.put("/edit-role/{user_id}")
def edit_role(
    user_id: int, 
    request: EditRoleRequest, 
    current_session: models.SystemSession = Depends(get_current_session), 
    db: Session = Depends(get_db)
):
    # Confirm the current user is an admin
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    
    if not current_user or current_user.user_role != schemas.UserRole.Admin:
        raise HTTPException(status_code=403, detail="Only Admin can edit user roles")

    user_to_edit = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user_to_edit:
        raise HTTPException(status_code=404, detail="User not found")

    user_to_edit.user_role = request.new_role
    db.commit()

    return {"message": f"Role updated successfully to {request.new_role}"}

# ==========================================
# Delete User Endpoint
# ==========================================

@app.delete("/delete-user/{user_id}")
def delete_user(
    user_id: int, 
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    # Verify that the current logged-in user is an Admin
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    
    if not current_user or current_user.user_role != schemas.UserRole.Admin:
        raise HTTPException(status_code=403, detail="Only Admin can delete users")

    # Prevent the Admin from deleting their own account while logged in
    if user_id == current_session.user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own admin account while logged in")

    # Check if the user to be deleted exists
    user_to_delete = db.query(models.User).filter(models.User.user_id == user_id).first()
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete the user (Cascade delete will automatically handle their sessions in PostgreSQL)
    db.delete(user_to_delete)
    db.commit()

    return {"message": f"User {user_to_delete.username} deleted successfully"}

# ==========================================
# System Status & Session Endpoints
# ==========================================

@app.get("/session-status")
def session_status(
    current_session: models.SystemSession = Depends(get_current_session)
):
    # If the user passes the get_current_session dependency, their session is active
    return {
        "active_session_id": current_session.session_id,
        "is_running": True,
        "user_id": current_session.user_id,
        "expires_at": current_session.expires_at
    }

@app.get("/sessions", response_model=list[schemas.SessionResponse])
def get_all_sessions(
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    # Only Admin can view all sessions history
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role != schemas.UserRole.Admin:
        raise HTTPException(status_code=403, detail="Only Admin can view all sessions")
        
    sessions = db.query(models.SystemSession).all()
    return sessions

# ==================================================
# Machine Control (START/STOP) & Status Endpoints
# ==================================================

class MachineCommand(BaseModel):
    command: str 

@app.post("/machine/control")
def control_machine(
    request: MachineCommand,
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    # Check if the user is an Admin or Operator
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to control the machine.")

    # Get MQTT connection details from .env
    broker = os.getenv("MQTT_BROKER")
    port = int(os.getenv("MQTT_PORT", 8883))
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")
    
    # Prepare authentication and TLS settings
    auth_dict = {'username': username, 'password': password} if username and password else None
    tls_dict = {'ca_certs': None} if port == 8883 else None

    # Send command to PLC via MQTT
    try:
        # Sending only one message then close connection
        publish.single(
            topic="factory/plc/commands",  # Topic for PLC commands
            payload=json.dumps({"command": request.command}),
            hostname=broker,
            port=port,
            auth=auth_dict,
            tls=tls_dict
        )
        return {"status": "success", "message": f"Command '{request.command}' sent to PLC."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to communicate with PLC: {str(e)}")

@app.get("/machine/status")
def get_machine_status(current_session: models.SystemSession = Depends(get_current_session)):
    """
    Fetches the current status of the machine based on latest current readings.
    """
    try:
        # Fetch the latest telemetry data from InfluxDB
        telemetry_data = get_latest_telemetry()
        
        # In case no telemetry data is available (Example: Machine not yet sending data)
        if not telemetry_data:
            return {
                "status": "success", 
                "machine_status": "UNKNOWN", 
                "current_amps": 0.0,
                "message": "No telemetry data found."
            }

        current_value = 0.0
        found_current = False
        last_timestamp = None

        # Iterate through the every dictionary in telemetry data
        for reading in telemetry_data:
            # Check if the "current" field exists in the reading
            if "current" in reading:
                current_value = float(reading["current"])
                last_timestamp = reading.get("timestamp")
                found_current = True
                break  # Found it! Stop iterating to save time.

        # If the "current" field is not found in any reading
        if not found_current or not last_timestamp:
             return {
                "status": "success", 
                "machine_status": "UNKNOWN", 
                "current_amps": 0.0,
                "message": "Current sensor data not found in recent telemetry."
            }

        # Calculate the age of the last reading
        # Convert the timestamp to a datetime object
        reading_time = datetime.fromisoformat(last_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        
        # Calculate the difference in seconds
        seconds_since_last_reading = (now - reading_time).total_seconds()

        # If the last reading is older than 10 seconds, mark the machine as offline
        if seconds_since_last_reading > 10:
            machine_state = "OFFLINE"  # Mark the machine as offline
            current_value = 0.0        # Set current to 0
        else:
            # If the last reading is recent, apply the threshold logic
            if current_value > 0.5:
                machine_state = "RUNNING"
            else:
                machine_state = "STOPPED"
            
        return {
            "status": "success",
            "machine_status": machine_state,
            "last_updated": last_timestamp,
            "data_age_seconds": round(seconds_since_last_reading, 1) # Age of the recent data in seconds
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch machine status: {str(e)}")

# ==========================================
# Inspection (Computer Vision) Endpoints
# ==========================================

class InspectionConfirmRequest(BaseModel):
    status: str         
    defect_type: str | None = None    # Accepts nulls if status is Good

# CONFIDENCE_THRESHOLD = 0.85

@app.post("/inspections", response_model=schemas.InspectionResponse)
def create_automated_inspection(
    sensor_id: str = Form(...),
    status: str = Form(...),
    defect_type: str = Form(None),
    confidence_score: float = Form(...),
    image_file: UploadFile = File(None), # Receive the actual image file
    db: Session = Depends(get_db)
):
    """
    Endpoint for the Computer Vision / AI Model to submit new inspection results along with the physical image.
    """
    temp_image_path = None
    
    # Ignore the image if the confidence score is high enough
    # if image_file and confidence_score >= CONFIDENCE_THRESHOLD:
        # print(f"Ignored image for high confidence ({confidence_score})")
        # image_file = None
    
    # Check if an image file is provided
    if image_file:
        # Generate a unique filename to avoid conflicts
        file_extension = image_file.filename.split('.')[-1]
        temp_filename = f"temp_{uuid.uuid4()}.{file_extension}"
        temp_image_path = f"./{temp_filename}"
        
        # Save the file temporarily on the server
        with open(temp_image_path, "wb") as buffer:
            shutil.copyfileobj(image_file.file, buffer)

    # Create the inspection record in the database
    new_inspection = models.Inspection(
        user_id=None,
        sensor_id=sensor_id,
        status=status,
        defect_type=defect_type,
        confidence_score=confidence_score,
        cv_image_url=temp_image_path  # Save the temporary path on the server
    )
    
    db.add(new_inspection)
    db.commit()
    db.refresh(new_inspection)
    
    return new_inspection

@app.put("/inspections/{inspection_id}/edit")
def edit_inspection(inspection_id: int,
                    request: InspectionConfirmRequest,
                    current_session: models.SystemSession = Depends(get_current_session),
                    db: Session = Depends(get_db)):
    
    # Confirm the current user is not a viewer
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to confirm or modify inspections.")
    
    inspection = db.query(models.Inspection).filter(models.Inspection.inspection_id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    inspection.user_id = current_session.user_id
    inspection.status = request.status
    inspection.defect_type = request.defect_type
    
    # Upload the image after correcting its classification
    old_path = inspection.cv_image_url
    if old_path and "cloudinary.com" not in old_path:
        new_category = request.defect_type or request.status
        new_path = move_to_confirmed_dataset(old_path, new_category)
        
        if new_path:
            inspection.cv_image_url = new_path
        else:
            # Handle the case where the image is lost due to server restart
            inspection.cv_image_url = None
    
    db.commit()
    return {
        "message": "Data updated and confirmed",
        "new_status": inspection.status,
        "new_category": inspection.defect_type,
        "image_url": inspection.cv_image_url
    }

@app.put("/inspections/{inspection_id}/confirm")
def confirm_only(inspection_id: int,
                 current_session: models.SystemSession = Depends(get_current_session),
                 db: Session = Depends(get_db)):
   
    # Confirm the current user is not a viewer
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to confirm or modify inspections.")
    
    inspection = db.query(models.Inspection).filter(models.Inspection.inspection_id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")
    
    inspection.user_id = current_session.user_id
    old_path = inspection.cv_image_url
    
    print(f"Inspection {inspection_id} has been confirmed by user.")
    
    # Upload the image after confirming its classification
    if old_path and "cloudinary.com" not in old_path:
        category = inspection.defect_type or inspection.status
        new_path = move_to_confirmed_dataset(old_path, category)
        
        if new_path:
            inspection.cv_image_url = new_path
        else:
            inspection.cv_image_url = None
            
    db.commit()

    return {
        "status": "success",
        "message": f"Inspection {inspection_id} confirmed",
        "final_status": inspection.status,
        "image_url": inspection.cv_image_url
    }

@app.put("/inspections/{inspection_id}/delete_image")
def reject_and_delete(inspection_id: int,
                      current_session: models.SystemSession = Depends(get_current_session),
                      db: Session = Depends(get_db)):
    
    # Confirm the current user is not a viewer
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to confirm or modify inspections.")
    
    inspection = db.query(models.Inspection).filter(models.Inspection.inspection_id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    inspection.user_id = current_session.user_id

    if inspection.cv_image_url:
        delete_inspection_image(inspection.cv_image_url)
        inspection.cv_image_url = None
        db.commit()

    return {
        "status": "success",
        "message": f"Inspection {inspection_id} image deleted."
    }

@app.get("/inspections/pending-review", response_model=list[schemas.InspectionResponse])
def get_pending_inspections(db: Session = Depends(get_db)):
    """
    Returns a list of inspections that have images need to be reviewed.
    """
    # SQL Query: SELECT * FROM inspections WHERE cv_image_url IS NOT NULL;
    pending_reviews = db.query(models.Inspection).filter(
        models.Inspection.cv_image_url.isnot(None)
    ).all()
    
    return pending_reviews

# ==========================================
# Telemetry (InfluxDB) Endpoints
# ==========================================

@app.get("/telemetry")
def get_telemetry(current_session: models.SystemSession = Depends(get_current_session)):
    """
    Fetches the latest sensor data from InfluxDB instead of PostgreSQL.
    Ideal for real-time monitoring.
    """
    try:
        data = get_latest_telemetry()
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch telemetry: {str(e)}")

@app.websocket("/ws/telemetry")
async def websocket_telemetry(
    websocket: WebSocket,
    session_id: UUID = Query(..., description="The Session ID obtained from login"),
    db: Session = Depends(get_db)
):
    """
    Live WebSocket stream, secured by Session ID via Query Parameter.
    """
    # Check if the session is valid before accepting the connection
    session = db.query(models.SystemSession).filter(
        models.SystemSession.session_id == session_id,
        models.SystemSession.expires_at > datetime.now()
    ).first()
    
    if not session:
        # If the session is invalid, reject the connection immediately with a policy violation code
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # If the session is valid, accept the connection
    await websocket.accept()
    print(f"User {session.user_id} connected to live telemetry.")
    
    try:
        while True:
            data = await asyncio.to_thread(get_latest_telemetry)
            if data:
                await websocket.send_json({"status": "success", "data": data})
            
            await asyncio.sleep(1.0)  
    except WebSocketDisconnect:
        print(f"User {session.user_id} disconnected from live telemetry.")
    except Exception as e:
        print(f"WebSocket connection dropped: {e}")

# ==========================================
# General Data Retrieval (GET) Endpoints
# ==========================================

@app.get("/users", response_model=list[schemas.UserResponse])
def get_users(
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    users = db.query(models.User).all()
    return users

@app.get("/users/{target_user_id}", response_model=schemas.UserResponse)
def get_user(
    target_user_id: int, 
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.user_id == target_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.get("/inspections", response_model=list[schemas.InspectionResponse])
def get_inspections(
    session_id: Optional[UUID] = None,  # Optional session ID for filtering
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    """
    Fetch inspections. Supports optional filtering by session_id.
    If no session_id is provided, it returns the latest 100 inspections for performance safety.
    """
    query = db.query(models.Inspection)

    # If a session ID is provided, filter inspections by that session
    if session_id:
        target_session = db.query(models.SystemSession).filter(
            models.SystemSession.session_id == session_id
        ).first()
        
        if not target_session:
            raise HTTPException(status_code=404, detail="Session not found")
            
        return query.filter(
            models.Inspection.user_id == target_session.user_id,
            models.Inspection.inspected_at >= target_session.created_at,
            models.Inspection.inspected_at <= target_session.expires_at
        ).all()

    # If no session ID is provided, return the latest 100 inspections
    return query.order_by(models.Inspection.inspected_at.desc()).limit(100).all()
    
# ==========================================
# Sensors Configuration Endpoints
# ==========================================

@app.post("/sensors", response_model=schemas.SensorResponse)
def create_sensor(sensor: schemas.SensorBase,
                  current_session: models.SystemSession = Depends(get_current_session),
                  db: Session = Depends(get_db)):
    """
    Adding a new sensor or camera to the system
    """
    # Check if a sensor with the same ID already exists
    existing_sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == sensor.sensor_id).first()
    if existing_sensor:
        raise HTTPException(status_code=400, detail="Sensor with this ID already exists.")
    
    # Create the new record
    new_sensor = models.Sensor(
        sensor_id=sensor.sensor_id,
        sensor_type=sensor.sensor_type,
        min_threshold=sensor.min_threshold,
        max_threshold=sensor.max_threshold,
        unit=sensor.unit,
        is_active=sensor.is_active
    )
    
    db.add(new_sensor)
    db.commit()
    db.refresh(new_sensor)
    return new_sensor

@app.get("/sensors", response_model=list[schemas.SensorResponse])
def get_all_sensors(current_session: models.SystemSession = Depends(get_current_session), db: Session = Depends(get_db)):
    """
    Fetch a list of all sensors for display in the Dashboard
    """
    sensors = db.query(models.Sensor).all()
    return sensors

@app.get("/sensors/{sensor_id}", response_model=schemas.SensorResponse)
def get_sensor(sensor_id: str, current_session: models.SystemSession = Depends(get_current_session), db: Session = Depends(get_db)):
    """
    Fetch data for a specific sensor based on its ID
    """
    sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return sensor

@app.put("/sensors/{sensor_id}/status")
def update_sensor_status(sensor_id: str, is_active: bool, current_session: models.SystemSession = Depends(get_current_session), db: Session = Depends(get_db)):
    """
    Activate or deactivate a specific sensor (e.g., during maintenance)
    """
    sensor = db.query(models.Sensor).filter(models.Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    
    sensor.is_active = is_active
    db.commit()
    return {"message": f"Sensor {sensor_id} status updated to {'Active' if is_active else 'Inactive'}"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)