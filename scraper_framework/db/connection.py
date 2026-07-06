"""Database connection pool setup."""

import os
from urllib.parse import quote

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def normalize_db_url(db_url: str) -> str:
    if not db_url.startswith(("postgresql://", "postgres://")):
        return db_url

    try:
        scheme, rest = db_url.split("://", 1)
    except ValueError:
        return db_url

    if "@" not in rest:
        return db_url

    credentials, host_part = rest.rsplit("@", 1)
    if ":" not in credentials:
        return db_url

    username, password = credentials.split(":", 1)
    encoded_password = quote(password, safe="")
    return f"{scheme}://{username}:{encoded_password}@{host_part}"


def get_database_url() -> str:
    return os.getenv("SUPABASE_DB_URL") or os.getenv("SUPABASE_URL") or os.getenv("DATABASE_URL", "")


def create_db_session(db_url: str | None = None, pool_size: int = 5):
    db_url = db_url or get_database_url()
    if not db_url:
        raise ValueError("Database URL must be provided via SUPABASE_DB_URL, SUPABASE_URL, or db_url argument.")

    db_url = normalize_db_url(db_url)
    engine = create_engine(db_url, pool_size=pool_size)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal
