import os
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@localhost/wikiofbabel"
)
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(engine)


def get_session():
    try:
        session = SessionLocal()
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_session)]
