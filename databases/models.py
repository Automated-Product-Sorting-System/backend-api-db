import enum
import uuid
from sqlalchemy import Column, Float, Integer, String, Boolean, DateTime, ForeignKey, Text, Numeric, Enum as SQLEnum, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from databases.postgres_conn import Base

class UserRole(str, enum.Enum):
    Admin = "Admin"
    Operator = "Operator"
    Viewer = "Viewer"

class InspectionStatus(str, enum.Enum):
    Good = "Good"
    Defected = "Defected"


# Users table
class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    user_role = Column(SQLEnum(UserRole), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)


# Sessions table
class SystemSession(Base):
    __tablename__ = "sessions"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        CheckConstraint('expires_at > created_at', name='check_session_expiration'),
    )


# Sensors table
class Sensor(Base):
    __tablename__ = "sensors"

    sensor_id = Column(String(100), primary_key=True)
    sensor_type = Column(String(50), nullable=False)
    min_threshold = Column(Numeric(10, 2), nullable=True)
    max_threshold = Column(Numeric(10, 2), nullable=True)
    unit = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint(
            'min_threshold IS NULL OR max_threshold IS NULL OR min_threshold < max_threshold', 
            name='check_sensor_thresholds'
        ),
    )


# Inspections table
class Inspection(Base):
    __tablename__ = "inspections"

    inspection_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True, index=True)
    sensor_id = Column(String(100), ForeignKey("sensors.sensor_id", ondelete="RESTRICT"), nullable=True, index=True)
    status = Column(SQLEnum(InspectionStatus), nullable=False, index=True)
    defect_type = Column(String(255), nullable=True)
    cv_image_url = Column(Text, nullable=True)
    inspected_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    confidence_score = Column(Float, nullable=True)