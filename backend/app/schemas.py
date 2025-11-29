from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

class TelemetryCreate(BaseModel):
    node_id: str
    timestamp: Optional[datetime] = None
    temperature_c: float
    humidity_pct: float
    battery_mv: int
    rssi_dbm: Optional[int] = None
    error_flags: int = 0

class InferenceCreate(BaseModel):
    node_id: str
    timestamp: Optional[datetime] = None
    model_type: str
    classification: Optional[str] = None
    confidence: Optional[float] = None
    anomaly_score: Optional[float] = None
    raw_outputs: Optional[Dict[str, float]] = None

class CommandCreate(BaseModel):
    node_id: str
    command_type: str
    params: Optional[Dict[str, Any]] = None

class CommandResponse(BaseModel):
    command_id: UUID
    status: str
