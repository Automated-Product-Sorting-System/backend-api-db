from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect, Query, status, File, UploadFile, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional
from passlib.context import CryptContext
import paho.mqtt.publish as publish
import json
import os
import math
import threading
import uvicorn
import asyncio
import uuid

# Internal imports
from core.utils import upload_image, move_cloudinary_asset, delete_cloudinary_asset
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
# Motor Control (START/STOP) & Status Endpoints
# ==================================================

class MotorCommand(BaseModel):
    command: str 

@app.post("/motor/control")
def control_motor(
    request: MotorCommand,
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    # Check if the user is an Admin or Operator (Viewers are not allowed to change system settings)
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to control the system.")

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

@app.get("/motor/status")
def get_motor_status(current_session: models.SystemSession = Depends(get_current_session)):
    """
    Fetches the current status of the motor by independently reading PLC status and Current sensor data.
    """
    try:
        telemetry_data = get_latest_telemetry()
        
        if not telemetry_data:
            return {
                "status": "success", 
                "motor_status": "UNKNOWN", 
                "current_amps": 0.0,
                "plc_logical_state": "UNKNOWN",
                "message": "No telemetry data found."
            }

        current_value = 0.0
        plc_status = "UNKNOWN"
        last_current_timestamp = None

        # Search through current reading data and PLC status
        for reading in telemetry_data:
            # Search for current reading
            if "current" in reading:
                current_value = float(reading["current"])
                last_current_timestamp = reading.get("timestamp")
            
            # Search for PLC status
            if reading.get("sensor_id") == "PLC" and "plc_status" in reading:
                plc_status = reading.get("plc_status")

        if not last_current_timestamp:
             return {
                "status": "success", 
                "motor_status": "UNKNOWN", 
                "current_amps": 0.0,
                "plc_logical_state": plc_status,
                "message": "Current sensor data not found in recent telemetry."
            }

        # Calculate the age of the last current reading to determine if the system is online
        reading_time = datetime.fromisoformat(last_current_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        seconds_since_last_reading = (now - reading_time).total_seconds()

        # Determine motor state based on PLC status and current reading
        if seconds_since_last_reading > 10:
            motor_state = "OFFLINE"
            current_value = 0.0
        else:
            if plc_status == "START" and current_value > 0.5:
                motor_state = "RUNNING"
            elif plc_status == "STOP" and current_value <= 0.5:
                motor_state = "STOPPED"
            elif plc_status == "START" and current_value <= 0.5:
                motor_state = "FAULT_NO_LOAD"
            elif plc_status == "STOP" and current_value > 0.5:
                motor_state = "FAULT_MANUAL_OVERRIDE"
            else:
                motor_state = "UNKNOWN_STATE"
            
        return {
            "status": "success",
            "motor_status": motor_state,
            "plc_logical_state": plc_status,
            "current_amps": current_value,
            "last_updated": last_current_timestamp,
            "data_age_seconds": round(seconds_since_last_reading, 1)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch motor status: {str(e)}")

# ==============================================
# Belt Speed Control & Display Speed Endpoints
# ==============================================

class SpeedCommand(BaseModel):
    speed_percentage: int = Field(..., ge=0, le=100, description="Speed percentage from 0 to 100")
    
# Hardware Constants
MAX_SPEED = 2.5            # Maximum speed in m/s
SPEED_TOLERANCE_PERCENT = 5.0  # Allowed deviation percentage    

@app.post("/belt/speed")
def set_belt_speed(
    request: SpeedCommand,
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    # Check if the user is an Admin or Operator (Viewers are not allowed to change system settings)
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to change belt speed.")

    broker = os.getenv("MQTT_BROKER")
    port = int(os.getenv("MQTT_PORT", 8883))
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")
    
    auth_dict = {'username': username, 'password': password} if username and password else None
    tls_dict = {'ca_certs': None} if port == 8883 else None

    try:
        # Send speed command and percentage via MQTT
        publish.single(
            topic="factory/plc/commands",
            payload=json.dumps({
                "command": "SET_SPEED", 
                "value": request.speed_percentage
            }),
            hostname=broker,
            port=port,
            auth=auth_dict,
            tls=tls_dict
        )
        return {"status": "success", "message": f"Speed command sent: {request.speed_percentage}%"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to communicate with PLC: {str(e)}")

@app.get("/belt/speed-status")
def get_speed_status(current_session: models.SystemSession = Depends(get_current_session)):
    """
    Fetches the actual speed vs PLC commanded speed and runs a smart correlation engine to detect mechanical failures or anomalies.
    """
    try:
        telemetry_data = get_latest_telemetry()
        
        if not telemetry_data:
            return {
                "status": "error", 
                "correlation_state": "UNKNOWN",
                "message": "No telemetry data found.",
                "max_speed_capacity": MAX_SPEED
            }

        actual_speed = 0.0
        plc_speed_raw = 0  # 0 to 255
        last_speed_timestamp = None

        # Dual-Lookup: Extract actual speed and PLC registered speed independently
        for reading in telemetry_data:
            # Assumes the physical speed sensor ID is 'Speed_01' and sends data as 'speed'
            if reading.get("sensor_id") == "Speed_01" and "speed_ms" in reading:
                actual_speed = float(reading["speed_ms"])
                last_speed_timestamp = reading.get("timestamp")
            
            # Extract the 8-bit speed value from the independent PLC record
            if reading.get("sensor_id") == "PLC" and "speed_register" in reading:
                plc_speed_raw = int(reading["speed_register"])

        if not last_speed_timestamp:
             return {
                 "status": "error", 
                 "correlation_state": "UNKNOWN",
                 "message": "Speed sensor data not found in recent telemetry.",
                 "max_speed_capacity": MAX_SPEED
             }

        # Normalization
        plc_target_percentage = (plc_speed_raw / 255.0) * 100.0
        actual_speed_percentage = (actual_speed / MAX_SPEED) * 100.0

        # Cap percentages at 100 to prevent UI issues if values slightly overshoot
        plc_target_percentage = min(plc_target_percentage, 100.0)
        actual_speed_percentage = min(actual_speed_percentage, 100.0)

        # Smart Correlation Engine
        speed_diff = actual_speed_percentage - plc_target_percentage
        speed_state = "UNKNOWN"

        if abs(speed_diff) <= SPEED_TOLERANCE_PERCENT:
            if plc_target_percentage == 0:
                speed_state = "IDLE"
            else:
                speed_state = "RUNNING_OPTIMAL"
        
        elif speed_diff < -SPEED_TOLERANCE_PERCENT:
            if plc_target_percentage > 0 and actual_speed_percentage <= 5.0:
                speed_state = "CRITICAL_JAM_OR_MOTOR_FAIL"
            else:
                speed_state = "UNDER_PERFORMING_CHECK_LOAD"
                
        elif speed_diff > SPEED_TOLERANCE_PERCENT:
            if plc_target_percentage == 0 and actual_speed_percentage > 5.0:
                speed_state = "MANUAL_OVERRIDE_OR_FREEWHEELING"
            else:
                speed_state = "OVER_SPEEDING_CALIBRATION_ERROR"

        return {
            "status": "success",
            "correlation_state": speed_state,
            "metrics": {
                "plc_target_percentage": round(plc_target_percentage, 1),
                "actual_speed_percentage": round(actual_speed_percentage, 1),
                "actual_speed": round(actual_speed, 2),
                "deviation_percentage": round(speed_diff, 1),
                "max_speed_capacity": MAX_SPEED
            },
            "last_updated": last_speed_timestamp
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate speed status: {str(e)}")

# ==========================================
# Inspection (Computer Vision) Endpoints
# ==========================================

def background_upload_task(inspection_id: int, image_bytes: bytes):
    """
    Background task to upload inspection image to Cloudinary.
    """
    db = SessionLocal() # Open a fresh database session for background task
    try:
        secure_url = upload_image(image_bytes, folder="Nexus_System/Pending")
        
        inspection = db.query(models.Inspection).filter(models.Inspection.inspection_id == inspection_id).first()
        if inspection:
            if secure_url:
                inspection.cv_image_url = secure_url
            else:
                inspection.cv_image_url = None # Clear URL if upload fails
            db.commit()
    finally:
        db.close() # Close the connection to prevent resource leaks (Memory Leak)

class InspectionConfirmRequest(BaseModel):
    status: str         
    defect_type: str | None = None    # Accepts nulls if status is Good

# CONFIDENCE_THRESHOLD = 0.85

@app.post("/inspections", response_model=schemas.InspectionResponse)
async def create_automated_inspection(
    background_tasks: BackgroundTasks,      # Inject background tasks service
    sensor_id: str = Form(...),
    status: str = Form(...),
    defect_type: str = Form(None),
    confidence_score: float = Form(...),
    image_file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """Create a new automated inspection with background image upload."""
    
    image_bytes = None
    
    # Ignore the image if the confidence score is high enough
    # if image_file and confidence_score >= CONFIDENCE_THRESHOLD:
        # print(f"Ignored image for high confidence ({confidence_score})")
        # image_file = None

    # Read the uploaded file into memory immediately (if provided)
    if image_file:
        image_bytes = await image_file.read()

    # Create the inspection record with a temporary flag until background upload completes
    new_inspection = models.Inspection(
        user_id=None,
        sensor_id=sensor_id,
        status=status,
        defect_type=defect_type,
        confidence_score=confidence_score,
        cv_image_url="uploading_in_background" if image_bytes else None
    )

    db.add(new_inspection)
    db.commit()
    db.refresh(new_inspection)

    # Queue the image for background upload and return response immediately
    if image_bytes:
        background_tasks.add_task(
            background_upload_task,
            new_inspection.inspection_id,
            image_bytes
        )

    return new_inspection

@app.put("/inspections/{inspection_id}/edit")
def edit_inspection(
    inspection_id: int,
    request: InspectionConfirmRequest,
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    """Update inspection data and move Cloudinary asset to the new category"""
    
    current_user = db.query(models.User).filter(
        models.User.user_id == current_session.user_id
    ).first()
    
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(
            status_code=403, 
            detail="Viewers are not allowed to confirm or modify inspections."
        )

    inspection = db.query(models.Inspection).filter(
        models.Inspection.inspection_id == inspection_id
    ).first()
    
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    inspection.user_id = current_session.user_id
    inspection.status = request.status
    inspection.defect_type = request.defect_type

    old_cloud_url = inspection.cv_image_url

    # Only move the image if it has already been uploaded (not in background queue)
    if old_cloud_url and old_cloud_url != "uploading_in_background":
        new_category = request.defect_type or request.status
        new_cloud_url = move_cloudinary_asset(old_cloud_url, new_category)

        if new_cloud_url:
            inspection.cv_image_url = new_cloud_url

    db.commit()

    return {
        "message": "Data updated and image moved on Cloudinary",
        "new_status": inspection.status,
        "new_category": inspection.defect_type,
        "image_url": inspection.cv_image_url
    }

@app.put("/inspections/{inspection_id}/confirm")
def confirm_only(
    inspection_id: int,
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to confirm or modify inspections.")
    
    inspection = db.query(models.Inspection).filter(models.Inspection.inspection_id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")
    
    inspection.user_id = current_session.user_id
    old_cloud_url = inspection.cv_image_url
    
    if old_cloud_url and old_cloud_url != "uploading_in_background":
        category = inspection.defect_type or inspection.status
        new_cloud_url = move_cloudinary_asset(old_cloud_url, category)
        
        if new_cloud_url:
            inspection.cv_image_url = new_cloud_url
            
    db.commit()

    return {
        "status": "success",
        "message": f"Inspection {inspection_id} confirmed and categorized",
        "final_status": inspection.status,
        "image_url": inspection.cv_image_url
    }

@app.put("/inspections/{inspection_id}/delete_image")
def reject_and_delete(
    inspection_id: int,
    current_session: models.SystemSession = Depends(get_current_session),
    db: Session = Depends(get_db)
):
    current_user = db.query(models.User).filter(models.User.user_id == current_session.user_id).first()
    if not current_user or current_user.user_role.value == "Viewer":
        raise HTTPException(status_code=403, detail="Viewers are not allowed to confirm or modify inspections.")
    
    inspection = db.query(models.Inspection).filter(models.Inspection.inspection_id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")

    inspection.user_id = current_session.user_id

    # Delete the image from Cloudinary
    if inspection.cv_image_url and inspection.cv_image_url != "uploading_in_background":
        delete_cloudinary_asset(inspection.cv_image_url)
        
    inspection.cv_image_url = None
    db.commit()

    return {
        "status": "success",
        "message": f"Inspection {inspection_id} image deleted from cloud."
    }

@app.get("/inspections/pending-review", response_model=schemas.PaginatedInspectionResponse)
def get_pending_inspections(
    page: int = Query(1, ge=1, description="Current page number"),
    size: int = Query(9, ge=1, le=100, description="Number of images per page"),
    db: Session = Depends(get_db)):
    """
    Returns a list of inspections that have images need to be reviewed.
    """
    # Main query that fetches all inspections that have images need review
    base_query = db.query(models.Inspection).filter(
        models.Inspection.cv_image_url.isnot(None)
    )
    
    # Calculate total image count and pages
    total_count = base_query.count()
    total_pages = math.ceil(total_count / size) if total_count > 0 else 1
    
    # Calculate the offset for the current page
    skip = (page - 1) * size
    
    # Fetch data for the current page only (ordered by oldest first)
    pending_reviews = base_query.order_by(
        models.Inspection.inspected_at.asc()
    ).offset(skip).limit(size).all()
    
    # Return the paginated results
    return {
        "data": pending_reviews,
        "meta": {
            "current_page": page,
            "page_size": size,
            "total_count": total_count,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1
        }
    }

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