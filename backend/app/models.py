from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    title: str
    url: str = Field(index=True, unique=True)
    source: str = Field(index=True)

    published_at: Optional[datetime] = Field(default=None, index=True)

    description: Optional[str] = None
    summary: Optional[str] = Field(default=None, index=True)
    content_hash: Optional[str] = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


