"""Create the ArtGuard schema without removing existing data."""
from alembic import op

from app.db import Base
from app import models  # noqa: F401 - register metadata

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # create_all only creates missing tables. It never drops or resets existing data.
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Deliberately non-destructive. Use a separately reviewed data migration for removals.
    pass
