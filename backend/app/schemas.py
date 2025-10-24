from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ArticleOut(BaseModel):
    id: int
    title: str
    url: str
    source: str
    published_at: Optional[datetime]
    description: Optional[str]
    summary: Optional[str]
    created_at: datetime

    class Config:
        orm_mode = True


