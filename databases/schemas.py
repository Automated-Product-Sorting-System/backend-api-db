from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional
from enum import Enum
from uuid import UUID 

# ==========================================
# Database Schema
# ==========================================

class UserRole(str, Enum):
    Admin = "Admin"
    Operator = "Operator"
    Viewer = "Viewer"

class InspectionStatus(str, Enum):
    Good = "Good"
    Defected = "Defected"
    Invalid = "Invalid"

class MotorCommandType(str, Enum):
    START = "START"
    STOP = "STOP"

# Users table
class UserBase(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    user_role: UserRole
    is_active: bool = True

class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)

class UserResponse(UserBase):
    user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# Sessions table
class SessionBase(BaseModel):
    user_id: int
    expires_at: datetime

class SessionCreate(SessionBase):
    pass

class SessionResponse(SessionBase):
    session_id: UUID 
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

# Sensors table
class SensorBase(BaseModel):
    sensor_id: str
    sensor_type: str
    min_threshold: Optional[float] = None
    max_threshold: Optional[float] = None
    unit: Optional[str] = None
    is_active: bool = True

class SensorResponse(SensorBase):
    model_config = ConfigDict(from_attributes=True)

# Inspections table
class InspectionBase(BaseModel):
    user_id: Optional[int] = None
    sensor_id: str
    status: InspectionStatus
    defect_type: Optional[str] = None
    cv_image_url: Optional[str] = None
    confidence_score: Optional[float] = None

class InspectionCreate(InspectionBase):
    pass

class InspectionResponse(InspectionBase):
    inspection_id: int
    inspected_at: datetime
    model_config = ConfigDict(from_attributes=True)
    
class PaginationMeta(BaseModel):
    current_page: int
    page_size: int
    total_count: int
    total_pages: int
    has_next: bool
    has_previous: bool

class PaginatedInspectionResponse(BaseModel):
    data: list[InspectionResponse]
    meta: PaginationMeta
    
# ==========================================
# Dashboard & Charts Schema
# ==========================================

# Schema for Line/Area Charts (e.g., InfluxDB Telemetry Data)
class TimeSeriesDataPoint(BaseModel):
    time: datetime
    value: float

class SensorChartResponse(BaseModel):
    sensor_id: str
    sensor_type: str
    unit: Optional[str] = None
    data_points: list[TimeSeriesDataPoint]

# Schema for Pie/Bar Charts (e.g., PostgreSQL Inspection Aggregations)
class DefectStat(BaseModel):
    category: str  # e.g., "Good", "Scratch", "Dent"
    count: int

class InspectionChartResponse(BaseModel):
    timeframe_hours: int
    total_inspections: int
    stats: list[DefectStat]