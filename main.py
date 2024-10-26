import os
import re
from typing import List

from fastapi.responses import HTMLResponse, RedirectResponse
import markdown
from openai import AsyncOpenAI
from sqlalchemy import Column, String, Text, create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.sql import text
from fastapi import FastAPI, HTTPException

app = FastAPI(title="Infinite Library")

import logging

log = logging.getLogger()

# Database setup
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@localhost/wikiofbabel"
)
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(engine)

envfile = os.path.expanduser("~/.openai")
if os.path.isfile(envfile):
    with open(os.path.expanduser("~/.openai"), encoding="utf-8") as fd:
        key = fd.read().strip()
        client = AsyncOpenAI(api_key=key)
else:
    client = AsyncOpenAI()


class Article(DeclarativeBase):
    __tablename__ = "articles"

    keyword = Column(String, primary_key=True, index=True)
    content = Column(Text)
    summary = Column(Text)


# Create the tsvector columns and indexes
def setup_full_text_search():
    with engine.connect() as conn:
        # Add tsvector columns if they don't exist
        conn.execute(
            text(
                """
            ALTER TABLE articles
            ADD COLUMN IF NOT EXISTS keyword_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', keyword)) STORED;

            ALTER TABLE articles
            ADD COLUMN IF NOT EXISTS content_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
        """
            )
        )

        # Create GIN indexes if they don't exist
        conn.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_articles_keyword_vector
            ON articles USING GIN(keyword_vector);

            CREATE INDEX IF NOT EXISTS idx_articles_content_vector
            ON articles USING GIN(content_vector);
        """
            )
        )

        conn.commit()


Base.metadata.create_all(bind=engine)
setup_full_text_search()


async def generate_article(keyword: str, db: sessionmaker) -> str:
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

    response = await client.chat.completions.create(
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
    keyword: str, db: sessionmaker, max_articles: int = 3
) -> List[Article]:
    """
    Find related articles using PostgreSQL full-text search.
    Returns a list of the most relevant articles.
    """
    # Create tsquery from keyword
    query = " | ".join(keyword.split())

    # Execute full-text search query
    sql = text(
        """
        SELECT
            keyword,
            content,
            ts_rank_cd(keyword_vector, to_tsquery('english', :query)) * 2 +
            ts_rank_cd(content_vector, to_tsquery('english', :query)) as rank
        FROM articles
        WHERE
            keyword_vector @@ to_tsquery('english', :query) OR
            content_vector @@ to_tsquery('english', :query)
        ORDER BY rank DESC
        LIMIT :limit
    """
    )

    return list(db.execute(sql, {"query": query, "limit": max_articles}))


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


async def generate_summary(content: str):
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": """You are a summary generator. You will summarise each message in less than
             100 words. The messages are wiki articles. You should only output the summary. Please try to retain
             as many keywords as possible from the original text
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
async def get_random_article():
    db = SessionLocal()
    # We try different sampling rates until we get a match
    for rate in [1, 10, 50, 75, 90, 100]:
        print(rate)
        result = db.execute(
            # Not random at all, but you ge the idea
            text(f"SELECT keyword FROM articles TABLESAMPLE BERNOULLI ({rate}) limit 1")
        ).first()
        if result is not None:
            break
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
async def page_list():
    db = SessionLocal()
    articles = db.query(Article).limit(50)
    main = "# The infinite library\n\nYou can go anywhere and we will auto-generate a new page for every keywords\n\n## The first 50 pages:\n"
    content = main + "\n".join("- [[" + a.keyword + "]]" for a in articles)
    return HTMLResponse(content=render_content("The infinite Library", content))


@app.get("/{keyword}")
async def get_article(keyword: str):
    # Convert URL format to storage format (replace underscores with spaces)
    keyword = keyword.replace("_", " ")

    # Clean the keyword (allow spaces but remove other special characters)
    keyword = re.sub(r"[^a-zA-Z0-9\s]", "", keyword).strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="Invalid keyword")

    db = SessionLocal()
    try:
        # Check if article exists in database
        article = db.query(Article).filter(Article.keyword == keyword).first()

        if not article:
            # Generate new article with context
            content = await generate_article(keyword, db)
            summary = await generate_summary(content)

            # Store in database
            article = Article(keyword=keyword, content=content, summary=summary)
            db.add(article)
            db.commit()
            db.refresh(article)

        return HTMLResponse(content=render_content(article.keyword, article.content))

    finally:
        db.close()
