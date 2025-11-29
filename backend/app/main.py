from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.database import init_db
from app.api import telemetry, commands, inference, logs

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="BeeWatch API", lifespan=lifespan)

app.include_router(telemetry.router, prefix="/api/v1")
app.include_router(inference.router, prefix="/api/v1")
app.include_router(commands.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")

@app.get("/health")
def health():
    return {"status": "healthy"}
