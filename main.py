import os
import csv
import io
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from database import (
    init_db,
    add_prospect,
    find_prospect_by_domain,
    get_prospect,
    list_prospects,
    search_prospects,
    list_best_prospects,
    update_prospect_research,
    replace_prospect_pages,
    list_prospect_pages,
    save_generated_message,
    list_generated_messages,
    update_status,
    update_manual_field,
    add_note,
    list_notes,
    mark_published,
    delete_prospect,
    get_report,
    list_all_for_export,
    clear_all,
)
from site_fetcher import normalize_url, get_domain, research_website
from ai_service import analyze_prospect_with_ai, generate_outreach_email, get_groq_client, clean_json_text


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_IDS_RAW = os.getenv("ALLOWED_CHAT_IDS", "")


VALID_STATUSES = [
    "new",
    "researched",
    "email_generated",
    "contacted",
    "replied",
    "accepted",
    "published",
    "rejected",
]


def get_allowed_chat_ids() -> set[int]:
    allowed_ids = set()

    for item in ALLOWED_CHAT_IDS_RAW.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            allowed_ids.add(int(item))
        except ValueError:
            continue

    return allowed_ids


def is_allowed_chat(telegram_chat_id: int) -> bool:
    allowed_ids = get_allowed_chat_ids()

    if not allowed_ids:
        return True

    return telegram_chat_id in allowed_ids


async def deny_if_not_allowed(update: Update) -> bool:
    chat_id = update.effective_chat.id

    if is_allowed_chat(chat_id):
        return False

    if update.message:
        await update.message.reply_text(
            "Доступ закритий 🔒\n\n"
            "Цей бот приватний."
        )

    if update.callback_query:
        await update.callback_query.answer("Доступ закритий", show_alert=True)

    return True


def build_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        ["📋 Prospects", "📊 Report"],
        ["⭐ Best", "📤 Export"],
        ["🔎 Search help", "➕ Help"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Додай URL або вибери кнопку",
    )


def build_prospect_keyboard(prospect_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔍 Research", callback_data=f"research:{prospect_id}"),
            InlineKeyboardButton("✉️ Email", callback_data=f"email:{prospect_id}"),
        ],
        [
            InlineKeyboardButton("🔁 Follow-up", callback_data=f"followup:{prospect_id}"),
            InlineKeyboardButton("🧲 Subjects", callback_data=f"subjects:{prospect_id}"),
        ],
        [
            InlineKeyboardButton("📬 Contact", callback_data=f"contact:{prospect_id}"),
            InlineKeyboardButton("👁 View", callback_data=f"view:{prospect_id}"),
        ],
        [
            InlineKeyboardButton("📨 Contacted", callback_data=f"status:{prospect_id}:contacted"),
            InlineKeyboardButton("✅ Accepted", callback_data=f"status:{prospect_id}:accepted"),
        ],
        [
            InlineKeyboardButton("📌 Published", callback_data=f"status:{prospect_id}:published"),
            InlineKeyboardButton("❌ Rejected", callback_data=f"status:{prospect_id}:rejected"),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def format_score(value) -> str:
    if value is None:
        return "—"
    return f"{value}/10"


def short(text: str | None, limit: int = 700) -> str:
    if not text:
        return "—"

    text = str(text).strip()

    if len(text) <= limit:
        return text

    return text[:limit] + "..."


def verdict_label(verdict: str | None) -> str:
    mapping = {
        "good": "✅ Good prospect",
        "maybe": "⚠️ Maybe",
        "skip": "❌ Skip",
    }
    return mapping.get(verdict or "", "—")


def format_prospect_short(prospect) -> str:
    return (
        f"ID: {prospect['id']}\n"
        f"URL: {prospect['url']}\n"
        f"Domain: {prospect.get('domain') or '—'}\n"
        f"Status: {prospect.get('status') or '—'}\n"
        f"Verdict: {verdict_label(prospect.get('verdict'))}\n"
        f"DR: {prospect.get('dr') or '—'}\n"
        f"Traffic: {prospect.get('traffic') or '—'}\n"
        f"Price: {prospect.get('price') or '—'}\n"
        f"Relevance: {format_score(prospect.get('relevance_score'))}\n"
        f"Quality: {format_score(prospect.get('quality_score'))}\n"
        f"Risk: {prospect.get('risk_level') or '—'}"
    )


def format_prospect_detail(prospect, pages=None, messages=None, notes=None) -> str:
    pages = pages or []
    messages = messages or []
    notes = notes or []

    text = (
        f"Prospect #{prospect['id']}\n\n"
        f"URL: {prospect['url']}\n"
        f"Domain: {prospect.get('domain') or '—'}\n"
        f"Status: {prospect.get('status') or '—'}\n"
        f"Verdict: {verdict_label(prospect.get('verdict'))}\n"
        f"Notes: {prospect.get('notes') or '—'}\n\n"

        f"Manual SEO fields:\n"
        f"DR: {prospect.get('dr') or '—'}\n"
        f"Traffic: {prospect.get('traffic') or '—'}\n"
        f"Price: {prospect.get('price') or '—'}\n"
        f"Contact person: {prospect.get('contact_person') or '—'}\n\n"

        f"Research:\n"
        f"Title: {prospect.get('site_title') or '—'}\n"
        f"Language: {prospect.get('language') or '—'}\n"
        f"Niche: {prospect.get('niche') or '—'}\n"
        f"Contact email: {prospect.get('contact_email') or '—'}\n"
        f"Contact page: {prospect.get('contact_page') or '—'}\n"
        f"Blog: {'yes' if prospect.get('has_blog') else 'no'}\n"
        f"Write for us: {'yes' if prospect.get('has_write_for_us') else 'no'}\n\n"
        f"Relevance: {format_score(prospect.get('relevance_score'))}\n"
        f"Quality: {format_score(prospect.get('quality_score'))}\n"
        f"Risk: {prospect.get('risk_level') or '—'}\n\n"
        f"Outreach angle:\n{short(prospect.get('outreach_angle'), 500)}\n\n"
        f"Summary:\n{short(prospect.get('summary'), 900)}\n"
    )

    if prospect.get("published_url"):
        text += (
            "\nPublished link:\n"
            f"URL: {prospect.get('published_url')}\n"
            f"Anchor: {prospect.get('anchor_text') or '—'}\n"
            f"Target: {prospect.get('target_url') or '—'}\n"
        )

    if pages:
        text += "\nPages collected:\n"
        for page in pages[:8]:
            text += f"- {page['page_type']}: {page['url']}\n"

    if notes:
        text += "\nNotes history:\n"
        for note in notes[:5]:
            created_at = note["created_at"].strftime("%Y-%m-%d") if note.get("created_at") else ""
            text += f"- {created_at}: {note['note']}\n"

    if messages:
        text += f"\nGenerated messages: {len(messages)}"

    return text


def format_prospects_list(prospects: list, title: str = "Твої prospects") -> str:
    if not prospects:
        return "Prospects поки немає."

    lines = [f"{title}:\n"]

    for prospect in prospects:
        lines.append(
            f"{prospect['id']}. {prospect['domain'] or prospect['url']}\n"
            f"   Status: {prospect['status']} | Verdict: {verdict_label(prospect.get('verdict'))}\n"
            f"   DR: {prospect.get('dr') or '—'} | Traffic: {prospect.get('traffic') or '—'} | Price: {prospect.get('price') or '—'}\n"
            f"   Relevance: {format_score(prospect.get('relevance_score'))}, "
            f"Quality: {format_score(prospect.get('quality_score'))}, "
            f"Risk: {prospect.get('risk_level') or '—'}"
        )

    return "\n\n".join(lines)


def build_help_text() -> str:
    return (
        "AI Outreach Research Agent 🤖\n\n"
        "Основні команди:\n"
        "/add URL notes — додати сайт\n"
        "/prospects — список сайтів\n"
        "/view ID — деталі сайту\n"
        "/research ID — дослідити сайт\n"
        "/email ID — згенерувати перший email\n"
        "/followup ID — згенерувати follow-up\n"
        "/status ID status — змінити статус\n"
        "/delete ID — видалити сайт\n"
        "/report — звіт по статусах\n"
        "/clear — очистити всі prospects\n\n"

        "Нові корисні команди:\n"
        "/set ID dr 55 — вручну додати DR\n"
        "/set ID traffic 12000 — вручну додати traffic\n"
        "/set ID price 80$ — вручну додати price\n"
        "/set ID contact Anna — contact person\n"
        "/contact ID — показати контакти\n"
        "/subjects ID — 3 subject lines\n"
        "/export — CSV файл\n"
        "/best — найкращі prospects\n"
        "/search query — пошук по базі\n"
        "/note ID text — додати нотатку\n"
        "/published ID published_url anchor target_url — зберегти опублікований лінк\n"
        "/myid — показати chat_id\n\n"

        "Статуси:\n"
        "new, researched, email_generated, contacted, replied, accepted, published, rejected\n\n"

        "Приклад:\n"
        "/add https://example.com target: guest post for pet niche"
    )


def generate_subject_lines(prospect: dict) -> list[str]:
    prompt = f"""
Generate 3 short outreach email subject lines for this prospect.

Prospect:
Domain: {prospect.get('domain')}
Site title: {prospect.get('site_title')}
Niche: {prospect.get('niche')}
Language: {prospect.get('language')}
Outreach angle: {prospect.get('outreach_angle')}
Notes: {prospect.get('notes')}

Rules:
- Return only JSON.
- JSON format: {{"subjects": ["subject 1", "subject 2", "subject 3"]}}
- Avoid spammy words.
- Keep subjects natural and short.
"""

    client = get_groq_client()
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are an SEO outreach specialist."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )

    import json
    raw_text = clean_json_text(response.choices[0].message.content)

    try:
        data = json.loads(raw_text)
        subjects = data.get("subjects", [])
        return [str(item) for item in subjects][:3]
    except Exception:
        return [line.strip("-• 1234567890. ") for line in raw_text.splitlines() if line.strip()][:3]


def parse_published_args(args: list[str]):
    if len(args) < 2:
        return None, None, None

    published_url = args[1]
    anchor_text = None
    target_url = None

    joined = " ".join(args[2:]).strip()

    if joined:
        if " target:" in joined:
            anchor_part, target_part = joined.split(" target:", 1)
            anchor_text = anchor_part.replace("anchor:", "").strip() or None
            target_url = target_part.strip() or None
        else:
            anchor_text = joined.replace("anchor:", "").strip() or None

    return published_url, anchor_text, target_url


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    await update.message.reply_text(
        "Привіт! Це AI Outreach Research Agent 🤖\n\n"
        "Я допоможу збирати сайти, досліджувати їх, генерувати outreach email-и "
        "і вести статуси.\n\n"
        + build_help_text(),
        reply_markup=build_main_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    await update.message.reply_text(
        build_help_text(),
        reply_markup=build_main_keyboard(),
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Твій chat_id:\n{update.effective_chat.id}"
    )


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    chat_id = update.effective_chat.id

    if not context.args:
        await update.message.reply_text(
            "Формат:\n/add URL notes\n\n"
            "Приклад:\n"
            "/add https://example.com target: guest post for pets"
        )
        return

    raw_url = context.args[0]
    notes = " ".join(context.args[1:]).strip() or None

    try:
        url = normalize_url(raw_url)
        domain = get_domain(url)

        existing = find_prospect_by_domain(chat_id, domain)
        if existing:
            await update.message.reply_text(
                "⚠️ Цей домен уже є в базі.\n\n"
                f"Existing prospect ID: {existing['id']}\n"
                f"Domain: {existing['domain']}\n"
                f"Status: {existing['status']}\n\n"
                "Я все одно додам новий запис, якщо це інша сторінка/ціль."
            )

        prospect_id = add_prospect(chat_id, url, domain, notes)
        prospect = get_prospect(prospect_id, chat_id)

        await update.message.reply_text(
            "Prospect додано ✅\n\n"
            + format_prospect_short(prospect),
            reply_markup=build_prospect_keyboard(prospect_id),
        )
    except Exception as error:
        logging.exception("Error while adding prospect")
        await update.message.reply_text(
            "Не зміг додати prospect 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def prospects_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    chat_id = update.effective_chat.id

    try:
        prospects = list_prospects(chat_id)

        if not prospects:
            await update.message.reply_text(
                "Prospects поки немає.\n\n"
                "Додай перший:\n"
                "/add https://example.com target: guest post"
            )
            return

        await update.message.reply_text(
            format_prospects_list(prospects),
            reply_markup=build_main_keyboard(),
            disable_web_page_preview=True,
        )
    except Exception as error:
        logging.exception("Error while listing prospects")
        await update.message.reply_text(
            "Не зміг отримати список prospects 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /view ID")
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        prospect = get_prospect(prospect_id, chat_id)

        if not prospect:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
            return

        pages = list_prospect_pages(prospect_id)
        messages = list_generated_messages(prospect_id)
        notes = list_notes(prospect_id)

        await update.message.reply_text(
            format_prospect_detail(prospect, pages, messages, notes),
            reply_markup=build_prospect_keyboard(prospect_id),
            disable_web_page_preview=True,
        )
    except ValueError:
        await update.message.reply_text("ID має бути числом.")
    except Exception as error:
        logging.exception("Error while viewing prospect")
        await update.message.reply_text(
            "Не зміг показати prospect 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def do_research(update: Update, prospect_id: int):
    chat_id = update.effective_chat.id
    prospect = get_prospect(prospect_id, chat_id)

    if not prospect:
        await update.effective_message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
        return

    message = await update.effective_message.reply_text(
        "🔍 Досліджую сайт...\n\n"
        "Це може зайняти 10–30 секунд."
    )

    website_data = research_website(prospect["url"])

    if not website_data.get("success"):
        await message.edit_text(
            "Не зміг дослідити сайт 😕\n\n"
            f"Причина: {website_data.get('error')}"
        )
        return

    ai_result = analyze_prospect_with_ai(prospect, website_data)

    contact_email = ai_result.get("contact_email")
    if not contact_email and website_data.get("all_emails"):
        contact_email = website_data["all_emails"][0]

    contact_page = ai_result.get("contact_page") or website_data.get("contact_page")

    update_prospect_research(
        prospect_id=prospect_id,
        telegram_chat_id=chat_id,
        site_title=ai_result.get("site_title"),
        meta_description=ai_result.get("meta_description"),
        language=ai_result.get("language"),
        niche=ai_result.get("niche"),
        contact_email=contact_email,
        contact_page=contact_page,
        has_blog=bool(ai_result.get("has_blog") or website_data.get("has_blog")),
        has_write_for_us=bool(
            ai_result.get("has_write_for_us") or website_data.get("has_write_for_us")
        ),
        relevance_score=ai_result.get("relevance_score"),
        quality_score=ai_result.get("quality_score"),
        risk_level=ai_result.get("risk_level"),
        outreach_angle=ai_result.get("outreach_angle"),
        summary=ai_result.get("summary"),
    )

    pages_to_save = []
    for page in website_data.get("pages", []):
        pages_to_save.append(
            {
                "url": page.get("url"),
                "page_type": page.get("page_type"),
                "title": page.get("title"),
                "h1": page.get("h1"),
                "text_excerpt": page.get("text_excerpt"),
                "emails_found": page.get("emails_found", []),
            }
        )

    replace_prospect_pages(prospect_id, pages_to_save)

    updated = get_prospect(prospect_id, chat_id)
    pages = list_prospect_pages(prospect_id)
    notes = list_notes(prospect_id)

    await message.edit_text(
        "Research completed ✅\n\n"
        + format_prospect_detail(updated, pages, notes=notes),
        reply_markup=build_prospect_keyboard(prospect_id),
        disable_web_page_preview=True,
    )


async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /research ID")
        return

    try:
        prospect_id = int(context.args[0])
        await do_research(update, prospect_id)
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def do_generate_email(update: Update, prospect_id: int, message_type: str):
    chat_id = update.effective_chat.id
    prospect = get_prospect(prospect_id, chat_id)

    if not prospect:
        await update.effective_message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
        return

    label = "follow-up" if message_type == "followup" else "first outreach email"

    message = await update.effective_message.reply_text(
        f"✍️ Генерую {label}..."
    )

    result = generate_outreach_email(prospect, message_type=message_type)

    subject = result.get("subject") or "Collaboration idea"
    body = result.get("body") or ""

    save_generated_message(
        prospect_id=prospect_id,
        message_type=message_type,
        subject=subject,
        body=body,
    )

    update_status(prospect_id, chat_id, "email_generated")

    await message.edit_text(
        f"Email generated ✅\n\n"
        f"Subject:\n{subject}\n\n"
        f"Body:\n{body}",
        reply_markup=build_prospect_keyboard(prospect_id),
        disable_web_page_preview=True,
    )


async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /email ID")
        return

    try:
        prospect_id = int(context.args[0])
        await do_generate_email(update, prospect_id, "first_email")
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def followup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /followup ID")
        return

    try:
        prospect_id = int(context.args[0])
        await do_generate_email(update, prospect_id, "followup")
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Формат:\n/status ID status\n\n"
            "Приклад:\n/status 4 contacted"
        )
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        status = context.args[1].lower().strip()

        if status not in VALID_STATUSES:
            await update.message.reply_text(
                "Невідомий статус.\n\n"
                "Доступні:\n" + ", ".join(VALID_STATUSES)
            )
            return

        updated = update_status(prospect_id, chat_id, status)

        if updated:
            await update.message.reply_text(f"Статус prospect {prospect_id} змінено на {status} ✅")
        else:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Формат:\n/set ID field value\n\n"
            "Приклади:\n"
            "/set 4 dr 55\n"
            "/set 4 traffic 12000\n"
            "/set 4 price 80$\n"
            "/set 4 contact Anna\n"
            "/set 4 email hello@site.com"
        )
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        field = context.args[1].lower().strip()
        value = " ".join(context.args[2:]).strip()

        updated = update_manual_field(prospect_id, chat_id, field, value)

        if updated:
            await update.message.reply_text(f"Поле `{field}` оновлено ✅", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
    except ValueError as error:
        await update.message.reply_text(f"Помилка значення: {error}")
    except Exception as error:
        logging.exception("Error while setting field")
        await update.message.reply_text(
            "Не зміг оновити поле 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /contact ID")
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        prospect = get_prospect(prospect_id, chat_id)

        if not prospect:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
            return

        pages = list_prospect_pages(prospect_id)
        emails = []

        for page in pages:
            raw = page.get("emails_found")
            if raw:
                for email in raw.split(","):
                    email = email.strip()
                    if email and email not in emails:
                        emails.append(email)

        text = (
            f"Contact data for prospect #{prospect_id}\n\n"
            f"Domain: {prospect.get('domain') or '—'}\n"
            f"Contact person: {prospect.get('contact_person') or '—'}\n"
            f"Main email: {prospect.get('contact_email') or '—'}\n"
            f"Contact page: {prospect.get('contact_page') or '—'}\n\n"
            "Emails found:\n"
        )

        if emails:
            text += "\n".join(f"- {email}" for email in emails[:10])
        else:
            text += "—"

        await update.message.reply_text(text, disable_web_page_preview=True)
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def subjects_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /subjects ID")
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        prospect = get_prospect(prospect_id, chat_id)

        if not prospect:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
            return

        subjects = generate_subject_lines(prospect)

        if not subjects:
            await update.message.reply_text("Не зміг згенерувати subject lines.")
            return

        text = "Subject line ideas 🧲\n\n"
        for index, subject in enumerate(subjects, start=1):
            text += f"{index}. {subject}\n"

        await update.message.reply_text(text)
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    chat_id = update.effective_chat.id

    try:
        rows = list_all_for_export(chat_id)

        if not rows:
            await update.message.reply_text("Немає prospects для export.")
            return

        output = io.StringIO()
        fieldnames = [
            "id",
            "domain",
            "url",
            "status",
            "verdict",
            "dr",
            "traffic",
            "price",
            "contact_person",
            "contact_email",
            "contact_page",
            "language",
            "niche",
            "relevance_score",
            "quality_score",
            "risk_level",
            "has_blog",
            "has_write_for_us",
            "outreach_angle",
            "summary",
            "published_url",
            "anchor_text",
            "target_url",
            "created_at",
            "updated_at",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})

        csv_bytes = io.BytesIO(output.getvalue().encode("utf-8-sig"))
        csv_bytes.name = "outreach_prospects.csv"

        await update.message.reply_document(
            document=InputFile(csv_bytes, filename="outreach_prospects.csv"),
            caption="Export готовий ✅"
        )
    except Exception as error:
        logging.exception("Error while exporting CSV")
        await update.message.reply_text(
            "Не зміг зробити export 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def best_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    chat_id = update.effective_chat.id
    prospects = list_best_prospects(chat_id)

    await update.message.reply_text(
        format_prospects_list(prospects, title="⭐ Best prospects"),
        disable_web_page_preview=True,
    )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /search query")
        return

    chat_id = update.effective_chat.id
    query = " ".join(context.args).strip()

    prospects = search_prospects(chat_id, query)

    await update.message.reply_text(
        format_prospects_list(prospects, title=f"Search results: {query}"),
        disable_web_page_preview=True,
    )


async def note_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if len(context.args) < 2:
        await update.message.reply_text("Формат: /note ID text")
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        note_text = " ".join(context.args[1:]).strip()

        saved = add_note(prospect_id, chat_id, note_text)

        if saved:
            await update.message.reply_text("Нотатку додано ✅")
        else:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def published_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Формат:\n"
            "/published ID published_url anchor text target: target_url\n\n"
            "Приклад:\n"
            "/published 4 https://site.com/article anchor: dog food guide target: https://client.com/dog-food"
        )
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        published_url, anchor_text, target_url = parse_published_args(context.args)

        if not published_url:
            await update.message.reply_text("Не бачу published_url.")
            return

        updated = mark_published(
            prospect_id=prospect_id,
            telegram_chat_id=chat_id,
            published_url=published_url,
            anchor_text=anchor_text,
            target_url=target_url,
        )

        if updated:
            await update.message.reply_text("Published link збережено ✅")
        else:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Формат: /delete ID")
        return

    chat_id = update.effective_chat.id

    try:
        prospect_id = int(context.args[0])
        deleted = delete_prospect(prospect_id, chat_id)

        if deleted:
            await update.message.reply_text(f"Prospect {prospect_id} видалено ✅")
        else:
            await update.message.reply_text(f"Не знайшов prospect з ID {prospect_id}.")
    except ValueError:
        await update.message.reply_text("ID має бути числом.")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    chat_id = update.effective_chat.id

    try:
        rows = get_report(chat_id)

        if not rows:
            await update.message.reply_text("Даних для звіту поки немає.")
            return

        counts = {row["status"]: row["count"] for row in rows}

        lines = ["Outreach report 📊\n"]

        for status in VALID_STATUSES:
            lines.append(f"{status}: {counts.get(status, 0)}")

        await update.message.reply_text("\n".join(lines))
    except Exception as error:
        logging.exception("Error while building report")
        await update.message.reply_text(
            "Не зміг створити звіт 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    chat_id = update.effective_chat.id

    try:
        clear_all(chat_id)
        await update.message.reply_text("Усі prospects очищено ✅")
    except Exception as error:
        logging.exception("Error while clearing data")
        await update.message.reply_text(
            "Не зміг очистити дані 😕\n\n"
            f"Технічна помилка:\n{type(error).__name__}: {error}"
        )


async def handle_keyboard_text(update: Update) -> bool:
    text = update.message.text
    chat_id = update.effective_chat.id

    if text == "📋 Prospects":
        prospects = list_prospects(chat_id)
        await update.message.reply_text(
            format_prospects_list(prospects),
            disable_web_page_preview=True,
        )
        return True

    if text == "📊 Report":
        rows = get_report(chat_id)
        if not rows:
            await update.message.reply_text("Даних для звіту поки немає.")
            return True

        counts = {row["status"]: row["count"] for row in rows}
        lines = ["Outreach report 📊\n"]

        for status in VALID_STATUSES:
            lines.append(f"{status}: {counts.get(status, 0)}")

        await update.message.reply_text("\n".join(lines))
        return True

    if text == "⭐ Best":
        prospects = list_best_prospects(chat_id)
        await update.message.reply_text(
            format_prospects_list(prospects, title="⭐ Best prospects"),
            disable_web_page_preview=True,
        )
        return True

    if text == "📤 Export":
        class FakeContext:
            args = []
        await export_command(update, FakeContext())
        return True

    if text == "🔎 Search help":
        await update.message.reply_text(
            "Пошук:\n/search query\n\n"
            "Приклад:\n/search pet\n/search accepted\n/search hello@"
        )
        return True

    if text == "➕ Help":
        await update.message.reply_text(build_help_text())
        return True

    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await deny_if_not_allowed(update):
        return

    if await handle_keyboard_text(update):
        return

    text = update.message.text.strip()

    if text.startswith("http://") or text.startswith("https://") or "." in text.split()[0]:
        parts = text.split()
        raw_url = parts[0]
        notes = " ".join(parts[1:]).strip() or None

        context.args = [raw_url]
        if notes:
            context.args += notes.split()

        await add_command(update, context)
        return

    await update.message.reply_text(
        "Не зрозумів повідомлення 🤔\n\n"
        "Додай сайт так:\n"
        "/add https://example.com target: guest post\n\n"
        "Або просто надішли URL з нотаткою."
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not query:
        return

    try:
        await query.answer()

        telegram_chat_id = query.message.chat_id
        data = query.data

        logging.info(f"Button clicked: chat_id={telegram_chat_id}, data={data}")

        if not is_allowed_chat(telegram_chat_id):
            await query.message.reply_text("Доступ закритий 🔒")
            return

        try:
            parts = data.split(":")
            action = parts[0]
            prospect_id = int(parts[1])
        except Exception:
            await query.message.reply_text(f"Не зрозумів кнопку: {data}")
            return

        if action == "view":
            prospect = get_prospect(prospect_id, telegram_chat_id)

            if not prospect:
                await query.message.reply_text("Prospect не знайдено.")
                return

            pages = list_prospect_pages(prospect_id)
            messages = list_generated_messages(prospect_id)
            notes = list_notes(prospect_id)

            await query.message.reply_text(
                format_prospect_detail(prospect, pages, messages, notes),
                reply_markup=build_prospect_keyboard(prospect_id),
                disable_web_page_preview=True,
            )
            return

        if action == "research":
            await do_research(update, prospect_id)
            return

        if action == "email":
            await do_generate_email(update, prospect_id, "first_email")
            return

        if action == "followup":
            await do_generate_email(update, prospect_id, "followup")
            return

        if action == "subjects":
            prospect = get_prospect(prospect_id, telegram_chat_id)
            if not prospect:
                await query.message.reply_text("Prospect не знайдено.")
                return

            subjects = generate_subject_lines(prospect)
            text = "Subject line ideas 🧲\n\n"
            for index, subject in enumerate(subjects, start=1):
                text += f"{index}. {subject}\n"

            await query.message.reply_text(text)
            return

        if action == "contact":
            prospect = get_prospect(prospect_id, telegram_chat_id)
            if not prospect:
                await query.message.reply_text("Prospect не знайдено.")
                return

            pages = list_prospect_pages(prospect_id)
            emails = []

            for page in pages:
                raw = page.get("emails_found")
                if raw:
                    for email in raw.split(","):
                        email = email.strip()
                        if email and email not in emails:
                            emails.append(email)

            text = (
                f"Contact data for prospect #{prospect_id}\n\n"
                f"Domain: {prospect.get('domain') or '—'}\n"
                f"Contact person: {prospect.get('contact_person') or '—'}\n"
                f"Main email: {prospect.get('contact_email') or '—'}\n"
                f"Contact page: {prospect.get('contact_page') or '—'}\n\n"
                "Emails found:\n"
            )

            if emails:
                text += "\n".join(f"- {email}" for email in emails[:10])
            else:
                text += "—"

            await query.message.reply_text(text, disable_web_page_preview=True)
            return

        if action == "status":
            if len(parts) < 3:
                await query.message.reply_text("Не передано статус.")
                return

            status = parts[2]
            updated = update_status(prospect_id, telegram_chat_id, status)

            if updated:
                await query.message.reply_text(
                    f"Статус prospect {prospect_id} змінено на {status} ✅",
                    reply_markup=build_prospect_keyboard(prospect_id),
                )
            else:
                await query.message.reply_text("Prospect не знайдено.")

            return

        await query.message.reply_text(f"Невідома дія з кнопки: {action}")

    except Exception as error:
        logging.exception("Error while handling button")

        try:
            await query.message.reply_text(
                "Сталася помилка при обробці кнопки 😕\n\n"
                f"Технічна помилка:\n{type(error).__name__}: {error}"
            )
        except Exception:
            pass


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Не знайдено TELEGRAM_BOT_TOKEN у Railway Variables.")

    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("prospects", prospects_command))
    app.add_handler(CommandHandler("view", view_command))
    app.add_handler(CommandHandler("research", research_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("followup", followup_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("set", set_command))
    app.add_handler(CommandHandler("contact", contact_command))
    app.add_handler(CommandHandler("subjects", subjects_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("best", best_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("note", note_command))
    app.add_handler(CommandHandler("published", published_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Outreach Agent is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
