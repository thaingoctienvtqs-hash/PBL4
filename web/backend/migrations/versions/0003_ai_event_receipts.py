"""Add retained AI receipts and attachments; never rewrite existing data."""
from alembic import op
import sqlalchemy as sa

revision = "0003_ai_event_receipts"
down_revision = "0002_add_stream_url_and_evidence"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "mssql":
        identity = bind.exec_driver_sql("SELECT DB_NAME()").scalar_one()
        if identity != "ArtGuard_Integration_TEST":
            raise RuntimeError("AI integration migration is approved only on the TEST database")
    elif bind.dialect.name != "sqlite":
        raise RuntimeError("Unsupported migration target")
    from app.ai_event_models import AiEventAttachment, AiEventReceipt
    tables = (AiEventReceipt.__table__, AiEventAttachment.__table__)
    inspector = sa.inspect(bind)
    for table in tables:
        if table.name in inspector.get_table_names():
            expected = set(table.columns.keys())
            observed = {column["name"] for column in inspector.get_columns(table.name)}
            if observed != expected:
                raise RuntimeError("Existing AI table has an incompatible column set: " + table.name)
        else:
            table.create(bind=bind, checkfirst=False)
        inspector = sa.inspect(bind)
    _verify_keys(bind, inspector)

def _verify_keys(bind, inspector):
    if bind.dialect.name == "mssql":
        # SQLAlchemy 2.1 MSSQL may not implement get_unique_constraints.
        # Read sys catalogs rather than assuming reflection support.
        query = (
            "SELECT c.name FROM sys.indexes i "
            "JOIN sys.index_columns ic ON i.object_id=ic.object_id AND i.index_id=ic.index_id "
            "JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id "
            "WHERE i.object_id=OBJECT_ID(N'dbo.ai_event_receipts') "
            "AND i.is_unique=1 AND i.name=N'uq_ai_event_producer_event' "
            "AND ic.key_ordinal>0 ORDER BY ic.key_ordinal"
        )
        columns = [row[0] for row in bind.exec_driver_sql(query).all()]
        if columns != ["producer_id", "event_id"]:
            raise RuntimeError("Existing AI receipt uniqueness is missing; no automatic repair")
        query = (
            "SELECT c.name FROM sys.indexes i "
            "JOIN sys.index_columns ic ON i.object_id=ic.object_id AND i.index_id=ic.index_id "
            "JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id "
            "WHERE i.object_id=OBJECT_ID(N'dbo.ai_event_attachments') "
            "AND i.is_primary_key=1 AND ic.key_ordinal>0 ORDER BY ic.key_ordinal"
        )
        columns = [row[0] for row in bind.exec_driver_sql(query).all()]
        if columns != ["receipt_id"]:
            raise RuntimeError("Existing AI attachment key is incompatible")
    else:
        constraints = inspector.get_unique_constraints("ai_event_receipts")
        if not any(set(row.get("column_names", [])) == {"producer_id", "event_id"} for row in constraints):
            raise RuntimeError("Existing AI receipt uniqueness is missing; no automatic repair")
        pk = inspector.get_pk_constraint("ai_event_attachments")
        if pk.get("constrained_columns") != ["receipt_id"]:
            raise RuntimeError("Existing AI attachment key is incompatible")


def downgrade():
    # Retain receipts, attachments and business records. No automatic drop.
    pass
