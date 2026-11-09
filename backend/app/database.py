from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


database_url = get_settings().database_url
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def create_database_tables() -> None:
    Base.metadata.create_all(bind=engine)
    if "is_verified" not in {
        column["name"] for column in inspect(engine).get_columns("invoices")
    }:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE invoices "
                    "ADD COLUMN is_verified BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
