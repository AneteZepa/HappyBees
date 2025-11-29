"""
HappyBees Backend - FastAPI Application

Entry point for the REST API server.
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager

from backend.app.database import init_db
from backend.app.api import telemetry, commands, inference, logs


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await init_db()
    yield


app = FastAPI(
    title="HappyBees API",
    description="Beehive Monitoring System API",
    version="0.7.0",
    lifespan=lifespan
)

# Include routers
app.include_router(telemetry.router, prefix="/api/v1")
app.include_router(inference.router, prefix="/api/v1")
app.include_router(commands.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}
