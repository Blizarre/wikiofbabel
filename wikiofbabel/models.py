from sqlalchemy import Column, Computed, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase


class WikiBase(DeclarativeBase):
    pass


class Article(WikiBase):
    __tablename__ = "articles"

    keyword = Column(String, primary_key=True, index=True)
    content = Column(Text)
    summary = Column(Text)
    words = Column(
        TSVECTOR, Computed("to_tsvector('english', keyword || ' ' || content)")
    )
    idx = Index("words_idx", words, postgresql_using="gin")
