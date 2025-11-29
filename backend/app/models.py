from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
import uuid

class Node(Base):
    __tablename__ = "nodes"
    node_id = Column(String(64), primary_key=True)
    name = Column(String(128))
    firmware_version = Column(String(32))
    last_seen_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)

class Telemetry(Base):
    __tablename__ = "telemetry"
    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    node_id = Column(String(64), ForeignKey("nodes.node_id"), primary_key=True)
    temperature_c = Column(Float)
    humidity_pct = Column(Float)
    battery_mv = Column(Integer)
    rssi_dbm = Column(Integer)
    error_flags = Column(Integer, default=0)

class InferenceResult(Base):
    __tablename__ = "inference_results"
    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    node_id = Column(String(64), ForeignKey("nodes.node_id"), primary_key=True)
    model_type = Column(String(16))
    classification = Column(String(64))
    confidence = Column(Float)
    anomaly_score = Column(Float)
    raw_outputs = Column(JSONB)

class Command(Base):
    __tablename__ = "commands"
    command_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(String(64), ForeignKey("nodes.node_id"))
    command_type = Column(String(32))
    params = Column(JSONB)
    status = Column(String(16), default="pending")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    sent_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

class DeviceLog(Base):
    __tablename__ = "device_logs"
    log_id = Column(Integer, primary_key=True, autoincrement=True)
    node_id = Column(String(64), ForeignKey("nodes.node_id"))
    message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
