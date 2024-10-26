import logging
import re
from typing import List

import markdown
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.sql import text

from wikiofbabel.clients import AsyncOpenAI

from .clients import OAIClient
from .db import DbSession
from .db import engine as db_engine
from .models import Article, WikiBase

log = logging.getLogger(__name__)


def lifespan(_app: FastAPI):
    WikiBase.metadata.create_all(bind=db_engine)
    yield


app = FastAPI(title="Infinite Library", lifespan=lifespan)


async def generate_article(keyword: str, db: DbSession, oai_client: AsyncOpenAI) -> str:
    """
    Generate an article using ChatGPT with context from related articles.
    """
    log.info("Generating article for %s", keyword)
    related_articles = await find_related_articles(keyword, db)
    log.info("Found %d related articles", len(related_articles))
    context = create_context_summary(related_articles)

    system_prompt = """You are writing articles for an encyclopedia from an alternate reality.
Your task is to create short, fascinating articles that maintain internal consistency with existing content.
Write in a professional, encyclopedia-like style.
Use markdown formatting.
Include many [[wiki style links]] to reference other potential articles. There should be at least a link per paragraph, and every place and person's name should have a link.
Be creative but maintain a serious, academic tone.
Articles should feel like they're from a complete, coherent alternate universe."""

    user_prompt = f"""Write an article about: {keyword}

Here is the context from related articles in our encyclopedia that you should maintain consistency with:

{context}

The article should include:
1. A clear introduction
2. Multiple sections with headers (using ## for h2 headers)
3. References to other articles using [[wiki style links]]
4. At least one quote from a fictional scholar or historical figure
5. Specific dates and events from our alternate timeline
6. A 'References' section at the end with 3-5 fictional sources
7. Maintains consistency with the context provided above

Format the article in markdown."""

    response = await oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,  # Balanced between creativity and consistency
        max_tokens=2000,  # Adjust based on desired article length
        presence_penalty=0.6,  # Encourage mentioning new concepts
        frequency_penalty=0.6,  # Discourage repetition
    )

    return response.choices[0].message.content


async def find_related_articles(
    keyword: str, db: DbSession, max_articles: int = 3
) -> List[Article]:
    """
    Find related articles using PostgreSQL full-text search.
    Returns a list of the most relevant articles.
    """
    # Create tsquery from keyword
    searched_words = " | ".join(keyword.split())

    rank_cd = func.ts_rank_cd(
        Article.words, func.to_tsquery("english", searched_words)
    ).label("rank")

    query = (
        select(Article.keyword, Article.content, rank_cd)
        .where(Article.words.bool_op("@@")(func.to_tsquery("english", searched_words)))
        .order_by(rank_cd.desc())
        .limit(max_articles)
    )

    return list(db.execute(query))


def create_context_summary(related_articles: List[Article]) -> str:
    """
    Create a summary of related articles for context.
    """
    if not related_articles:
        return "No related articles found."

    summary = "Related articles in our encyclopedia:\n\n"
    for article in related_articles:
        summary += f"From article about {article.keyword}:\n{summary}\n\n"

    return summary


async def generate_summary(content: str, oai_client: AsyncOpenAI):
    response = await oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": """You are a summary generator for a full text search engine. You will summarise each
                message in less than 100 words. The messages are wiki articles. You should only output the summary.
                Please try to retain as many keywords as possible from the original text.
             """,
            },
            {"role": "user", "content": content},
        ],
        temperature=0.7,  # Balanced between creativity and consistency
        max_tokens=2000,  # Adjust based on desired article length
    )

    return response.choices[0].message.content


def process_markdown(content: str) -> str:
    """
    Convert markdown to HTML and process wiki-style links.
    """

    def wiki_link_replacer(match):
        page_name = match.group(1)
        url_name = page_name.replace(" ", "_")
        return f'<a href="/{url_name}">{page_name}</a>'

    content = re.sub(r"\[\[(.*?)\]\]", wiki_link_replacer, content)
    return markdown.markdown(content)


@app.get("/random")
async def get_random_article(db: DbSession):
    # We try different sampling rates until we get a match
    for rate in [1, 10, 50, 75, 90, 100]:
        print(rate)
        result = db.execute(
            # Not random at all, but you ge the idea
            text(f"SELECT keyword FROM articles TABLESAMPLE BERNOULLI ({rate}) limit 1")
        ).first()
        if result is not None:
            break
    if result is None:
        return HTMLResponse(
            content=render_content(
                "Nowhere", "Do you want to try something? Like [[The great Emu War]]"
            )
        )
    return RedirectResponse(url="/" + result[0].replace(" ", "_"))


def render_content(title: str, content: str):
    html_content = process_markdown(content)
    return f"""
    <!DOCTYPE html>
    <html>
        <head>
            <title>{title} - Infinite Library</title>
            <style>
                body {{
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                    font-family: system-ui, -apple-system, sans-serif;
                    line-height: 1.6;
                }}
            </style>
        </head>
        <body>
            {html_content}

            <hr>
            <i><a href="/random">Random page</a>
        </body>
    </html>
    """


@app.get("/")
async def page_list(db: DbSession):
    articles = db.query(Article).limit(50)
    main = "# The infinite library\n\nYou can go anywhere and we will auto-generate a new page for every keywords\n\n## The first 50 pages:\n"
    content = main + "\n".join("- [[" + a.keyword + "]]" for a in articles)
    return HTMLResponse(content=render_content("The infinite Library", content))


@app.get("/favicon.ico")
async def favicon():
    raise HTTPException(404)


@app.get("/{keyword}")
async def get_article(keyword: str, db: DbSession, oai_client: OAIClient):
    # Very simplistic keyword conversion: _ become spaces, any other non-alphanumerical character
    # is ignored
    keyword = keyword.replace("_", " ")
    keyword = re.sub(r"[^a-zA-Z0-9\s]", "", keyword).strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="Invalid keyword")

    article = db.query(Article).filter(Article.keyword == keyword).first()

    if not article:
        content = await generate_article(keyword, db, oai_client)
        summary = await generate_summary(content, oai_client)

        article = Article(keyword=keyword, content=content, summary=summary)
        db.add(article)
        db.commit()
        db.refresh(article)

    return HTMLResponse(content=render_content(article.keyword, article.content))
