from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from alembic.config import Config
from alembic import command

from app.db.repositories.water_body_repository import WaterBodyRepository
from app.schemas.water_body import WaterBodyCreate


def test_database_persistence_across_sessions(tmp_path: Path):
    """
    Test persistence across restarts:
    1. Apply migrations to a file-based SQLite database.
    2. Open engine/session and insert a WaterBody.
    3. Close session and dispose the engine completely (simulating process restart).
    4. Reopen new engine/session from the same SQLite file.
    5. Retrieve the record and verify data integrity.
    """
    db_file = tmp_path / "persistence_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    # Step 1: Run Alembic migration to create schema
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    engine1 = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine1.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    # Step 2: Open session 1 and write entity
    Session1 = sessionmaker(bind=engine1)
    with Session1() as session:
        repo = WaterBodyRepository(session)
        created = repo.create(
            WaterBodyCreate(
                name="Loktak Lake",
                country="India",
                state_province="Manipur",
                district="Bishnupur",
                source="survey",
                source_id="loktak-persist-1",
                area_sq_km=287.0,
            )
        )
        saved_id = created.id
        assert saved_id is not None

    # Step 3: Shutdown / dispose engine 1
    engine1.dispose()

    # Step 4 & 5: Open brand new engine 2 and retrieve
    engine2 = create_engine(db_url, connect_args={"check_same_thread": False})
    Session2 = sessionmaker(bind=engine2)
    with Session2() as session:
        repo2 = WaterBodyRepository(session)
        retrieved = repo2.get_by_id(saved_id)
        assert retrieved is not None
        assert retrieved.name == "Loktak Lake"
        assert retrieved.country == "India"
        assert retrieved.area_sq_km == 287.0
        assert retrieved.source_id == "loktak-persist-1"

    engine2.dispose()
