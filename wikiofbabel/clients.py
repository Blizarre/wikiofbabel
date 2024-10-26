import os
from typing import Annotated

from fastapi import Depends
from openai import AsyncOpenAI

envfile = os.path.expanduser("~/.openai")
if os.path.isfile(envfile):
    with open(os.path.expanduser("~/.openai"), encoding="utf-8") as fd:
        key = fd.read().strip()
        oai_client = AsyncOpenAI(api_key=key)
else:
    oai_client = AsyncOpenAI()


def get_oaiclient():
    yield oai_client


OAIClient = Annotated[AsyncOpenAI, Depends(get_oaiclient)]
