from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Alert, Artwork, Device, Location, ModelVersion, Role, User
from seed_demo import run_seed


def test_demo_seed_is_idempotent():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        first = run_seed(factory)
        second = run_seed(factory)

        assert first == second
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(Role)) == 3
            assert db.scalar(select(func.count()).select_from(User)) == 3
            assert db.scalar(select(func.count()).select_from(Location)) == 3
            assert db.scalar(select(func.count()).select_from(Artwork)) == 8
            assert db.scalar(select(func.count()).select_from(Device)) == 4
            assert db.scalar(select(func.count()).select_from(Alert)) == 24
            assert db.scalar(select(func.count()).select_from(ModelVersion)) == 3
    finally:
        engine.dispose()
