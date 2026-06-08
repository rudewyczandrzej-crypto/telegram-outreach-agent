import os
from datetime import datetime

import psycopg
from psycopg.rows import dict_row


def get_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL не знайдено у Railway Variables")

    return psycopg.connect(database_url, row_factory=dict_row)


def init_db():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS prospects (
                    id SERIAL PRIMARY KEY,
                    telegram_chat_id BIGINT NOT NULL,
                    url TEXT NOT NULL,
                    domain TEXT,
                    notes TEXT,
                    status TEXT DEFAULT 'new',

                    site_title TEXT,
                    meta_description TEXT,
                    language TEXT,
                    niche TEXT,

                    contact_email TEXT,
                    contact_page TEXT,
                    has_blog BOOLEAN DEFAULT FALSE,
                    has_write_for_us BOOLEAN DEFAULT FALSE,

                    relevance_score INTEGER,
                    quality_score INTEGER,
                    risk_level TEXT,
                    outreach_angle TEXT,
                    summary TEXT,

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS prospect_pages (
                    id SERIAL PRIMARY KEY,
                    prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    page_type TEXT,
                    title TEXT,
                    h1 TEXT,
                    text_excerpt TEXT,
                    emails_found TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_messages (
                    id SERIAL PRIMARY KEY,
                    prospect_id INTEGER REFERENCES prospects(id) ON DELETE CASCADE,
                    message_type TEXT NOT NULL,
                    subject TEXT,
                    body TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            conn.commit()


def add_prospect(telegram_chat_id: int, url: str, domain: str, notes: str | None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prospects (
                    telegram_chat_id,
                    url,
                    domain,
                    notes,
                    status
                )
                VALUES (%s, %s, %s, %s, 'new')
                RETURNING id;
                """,
                (telegram_chat_id, url, domain, notes),
            )
            row = cur.fetchone()
            conn.commit()
            return row["id"]


def get_prospect(prospect_id: int, telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM prospects
                WHERE id = %s AND telegram_chat_id = %s;
                """,
                (prospect_id, telegram_chat_id),
            )
            return cur.fetchone()


def list_prospects(telegram_chat_id: int, limit: int = 20):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM prospects
                WHERE telegram_chat_id = %s
                ORDER BY id DESC
                LIMIT %s;
                """,
                (telegram_chat_id, limit),
            )
            return cur.fetchall()


def update_prospect_research(
    prospect_id: int,
    telegram_chat_id: int,
    site_title: str | None,
    meta_description: str | None,
    language: str | None,
    niche: str | None,
    contact_email: str | None,
    contact_page: str | None,
    has_blog: bool,
    has_write_for_us: bool,
    relevance_score: int | None,
    quality_score: int | None,
    risk_level: str | None,
    outreach_angle: str | None,
    summary: str | None,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE prospects
                SET
                    site_title = %s,
                    meta_description = %s,
                    language = %s,
                    niche = %s,
                    contact_email = %s,
                    contact_page = %s,
                    has_blog = %s,
                    has_write_for_us = %s,
                    relevance_score = %s,
                    quality_score = %s,
                    risk_level = %s,
                    outreach_angle = %s,
                    summary = %s,
                    status = 'researched',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND telegram_chat_id = %s;
                """,
                (
                    site_title,
                    meta_description,
                    language,
                    niche,
                    contact_email,
                    contact_page,
                    has_blog,
                    has_write_for_us,
                    relevance_score,
                    quality_score,
                    risk_level,
                    outreach_angle,
                    summary,
                    prospect_id,
                    telegram_chat_id,
                ),
            )
            conn.commit()


def replace_prospect_pages(prospect_id: int, pages: list[dict]):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM prospect_pages
                WHERE prospect_id = %s;
                """,
                (prospect_id,),
            )

            for page in pages:
                cur.execute(
                    """
                    INSERT INTO prospect_pages (
                        prospect_id,
                        url,
                        page_type,
                        title,
                        h1,
                        text_excerpt,
                        emails_found
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        prospect_id,
                        page.get("url"),
                        page.get("page_type"),
                        page.get("title"),
                        page.get("h1"),
                        page.get("text_excerpt"),
                        ", ".join(page.get("emails_found", [])),
                    ),
                )

            conn.commit()


def list_prospect_pages(prospect_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM prospect_pages
                WHERE prospect_id = %s
                ORDER BY id ASC;
                """,
                (prospect_id,),
            )
            return cur.fetchall()


def save_generated_message(
    prospect_id: int,
    message_type: str,
    subject: str | None,
    body: str,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generated_messages (
                    prospect_id,
                    message_type,
                    subject,
                    body
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (prospect_id, message_type, subject, body),
            )
            row = cur.fetchone()
            conn.commit()
            return row["id"]


def list_generated_messages(prospect_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM generated_messages
                WHERE prospect_id = %s
                ORDER BY id DESC;
                """,
                (prospect_id,),
            )
            return cur.fetchall()


def update_status(prospect_id: int, telegram_chat_id: int, status: str) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE prospects
                SET status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND telegram_chat_id = %s
                RETURNING id;
                """,
                (status, prospect_id, telegram_chat_id),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None


def delete_prospect(prospect_id: int, telegram_chat_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM prospects
                WHERE id = %s AND telegram_chat_id = %s
                RETURNING id;
                """,
                (prospect_id, telegram_chat_id),
            )
            row = cur.fetchone()
            conn.commit()
            return row is not None


def get_report(telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM prospects
                WHERE telegram_chat_id = %s
                GROUP BY status
                ORDER BY status ASC;
                """,
                (telegram_chat_id,),
            )
            return cur.fetchall()


def clear_all(telegram_chat_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM prospects
                WHERE telegram_chat_id = %s;
                """,
                (telegram_chat_id,),
            )
            conn.commit()
