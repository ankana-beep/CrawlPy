"""Database models and schemas."""

from sqlalchemy import BigInteger, Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import synonym

Base = declarative_base()


class ScrapedItem(Base):
    __tablename__ = "crawl"

    id = Column(BigInteger, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    url = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    text = Column(Text, nullable=True)
    json_data = Column(JSONB, nullable=True)

    # Backwards-compatible aliases for older code paths / payloads
    content = synonym("text")
    data = synonym("json_data")
