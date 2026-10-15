from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func, select, true
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user
from app.models import Alert, Artwork, Device, Location, User

router = APIRouter(tags=["dashboard and reports"])


def dashboard_payload(db: Session, days: int):
    today = datetime.utcnow().date()
    start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    alert_day = (
        extract("year", Alert.detected_at),
        extract("month", Alert.detected_at),
        extract("day", Alert.detected_at),
    )
    alerts_by_day = db.execute(
        select(*alert_day, func.count(Alert.id))
        .where(Alert.detected_at >= start)
        .group_by(*alert_day)
        .order_by(*alert_day)
    ).all()
    day_map = {date(int(year), int(month), int(day)).isoformat(): count for year, month, day, count in alerts_by_day}
    trend = [{"date": (today - timedelta(days=offset)).isoformat(), "count": day_map.get((today - timedelta(days=offset)).isoformat(), 0)} for offset in reversed(range(days))]
    severity_rows = db.execute(select(Alert.severity, func.count(Alert.id)).where(Alert.detected_at >= start).group_by(Alert.severity)).all()
    device_rows = db.execute(select(Device.status, func.count(Device.id)).group_by(Device.status)).all()
    total_artworks = db.scalar(select(func.count(Artwork.id))) or 0
    total_devices = db.scalar(select(func.count(Device.id))) or 0
    active_devices = db.scalar(select(func.count(Device.id)).where(Device.status == "online")) or 0
    offline_devices = db.scalar(select(func.count(Device.id)).where(Device.status == "offline")) or 0
    pending_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.status.in_(["new", "acknowledged", "investigating"]))) or 0
    critical_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.severity == "critical", Alert.status.in_(["new", "acknowledged", "investigating"]))) or 0
    recent = db.scalars(select(Alert).order_by(Alert.detected_at.desc()).limit(8)).all()
    from app.api.resources import alert_output
    return {
        "metrics": {"artworks": total_artworks, "devices": total_devices, "active_devices": active_devices, "offline_devices": offline_devices, "pending_alerts": pending_alerts, "critical_alerts": critical_alerts},
        "trend": trend,
        "severity": [{"name": name, "value": value} for name, value in sorted(severity_rows)],
        "device_status": [{"name": name, "value": value} for name, value in sorted(device_rows)],
        "recent_alerts": [alert_output(row).model_dump(mode="json") for row in recent],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_mode": "demo",
    }


@router.get("/dashboard")
def dashboard(days: int = Query(7, ge=7, le=30), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return dashboard_payload(db, days)


@router.get("/reports/summary")
def report_summary(days: int = Query(30, ge=7, le=90), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = dashboard_payload(db, days)
    active_locations = db.scalar(select(func.count(Location.id)).where(Location.is_active == true())) or 0
    return {**payload, "period_days": days, "location_count": active_locations}
