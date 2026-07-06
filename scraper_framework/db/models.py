"""Database models and schemas."""

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class ScrapedItem(Base):
    __tablename__ = "scraped_items"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(1024), nullable=False)
    title = Column(String(512), nullable=True)
    content = Column(Text, nullable=True)
