import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import admin, alerts, auth, dashboard, evidence, resources
from app.artwork_images import ARTWORK_UPLOAD_DIR, router as artwork_images_router
from app.core.settings import settings
from app.db import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("artguard")

app = FastAPI(
    title="ArtGuard API",
    description="API quản lý bộ sưu tập và sự kiện giám sát mô phỏng. Không kết nối AI hoặc camera thật.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])
from app.api.evidence import EVIDENCE_UPLOAD_DIR

ARTWORK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EVIDENCE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads/artworks", StaticFiles(directory=str(ARTWORK_UPLOAD_DIR), check_dir=True), name="artwork-uploads")


@app.middleware("http")
async def safe_unhandled_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled request failure at %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Đã xảy ra lỗi nội bộ. Vui lòng thử lại sau."})


@app.get("/health", tags=["system"])
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected", "mode": "demo"}
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable", "mode": "demo", "message": "Kiểm tra dịch vụ SQL Server, ODBC Driver và cấu hình web/.env"})


for route_module in (auth, resources, alerts, dashboard, admin, evidence):
    app.include_router(route_module.router, prefix="/api/v1")
app.include_router(artwork_images_router, prefix="/api/v1")
