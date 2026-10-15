from sqlalchemy import extract, func, select, true
from sqlalchemy.dialects import mssql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.settings import Settings
from app.models import Alert, AlertNote, Base, Location, SystemSetting, User


def test_default_database_url_uses_verified_sql_server_driver():
    settings = Settings(_env_file=None, app_env="development")
    url = settings.database_url

    assert settings.app_env == "development"
    assert url.drivername == "mssql+pyodbc"
    assert url.host == "localhost"
    assert url.port == 1433
    assert url.database == "pbl4_art_guard"
    assert url.query["driver"] == "ODBC Driver 17 for SQL Server"
    assert url.query["Trusted_Connection"] == "yes"
    assert url.query["Encrypt"] == "yes"
    assert url.query["TrustServerCertificate"] == "no"


def test_named_instance_uses_instance_instead_of_port():
    settings = Settings(_env_file=None, db_instance="ARTGUARD")

    assert settings.database_url.host == "localhost\\ARTGUARD"
    assert settings.database_url.port is None


def test_sql_auth_password_is_url_encoded_and_hidden_by_default():
    settings = Settings(
        _env_file=None,
        db_trusted_connection=False,
        db_username="artguard-app",
        db_password="pa:ss%word",
    )

    assert settings.database_url.username == "artguard-app"
    assert settings.database_url.password == "pa:ss%word"
    assert "pa:ss%word" not in str(settings.database_url)
    assert "pa%3Ass%25word" in settings.database_url.render_as_string(hide_password=False)
    assert "Trusted_Connection" not in settings.database_url.query


def test_models_compile_with_sql_server_unicode_identity_and_boolean_types():
    user_ddl = str(CreateTable(User.__table__).compile(dialect=mssql.dialect()))
    alert_ddl = str(CreateTable(Alert.__table__).compile(dialect=mssql.dialect()))
    alert_note_ddl = str(CreateTable(AlertNote.__table__).compile(dialect=mssql.dialect()))
    setting_ddl = str(CreateTable(SystemSetting.__table__).compile(dialect=mssql.dialect()))

    assert "IDENTITY" in user_ddl
    assert "NVARCHAR(255)" in user_ddl
    assert "BIT" in user_ddl
    assert "NVARCHAR(max)" in alert_ddl
    assert "ON DELETE NO ACTION" in alert_note_ddl
    assert "RESTRICT" not in alert_note_ddl
    assert "NVARCHAR(max)" in setting_ddl

    for table in Base.metadata.sorted_tables:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=mssql.dialect()))
        for index in table.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=mssql.dialect()))


def test_daily_dashboard_query_compiles_to_sql_server_datepart():
    query = select(
        extract("year", Alert.detected_at),
        extract("month", Alert.detected_at),
        extract("day", Alert.detected_at),
        func.count(Alert.id),
    ).group_by(
        extract("year", Alert.detected_at),
        extract("month", Alert.detected_at),
        extract("day", Alert.detected_at),
    )

    compiled = str(query.compile(dialect=mssql.dialect()))
    assert "DATEPART(year" in compiled
    assert "DATEPART(month" in compiled
    assert "DATEPART(day" in compiled


def test_sql_server_boolean_filter_uses_comparison_not_is_true():
    compiled = str(select(Location.id).where(Location.is_active == true()).compile(dialect=mssql.dialect()))

    assert "locations.is_active = 1" in compiled
    assert "locations.is_active IS 1" not in compiled
