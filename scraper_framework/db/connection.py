"""Database connection pool setup."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def create_db_session(db_url: str, pool_size: int = 5):
    engine = create_engine(db_url, pool_size=pool_size)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal
