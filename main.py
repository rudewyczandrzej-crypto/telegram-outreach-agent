import os
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
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
    get_prospect,
    list_prospects,
    update_prospect_research,
    replace_prospect_pages,
    list_prospect_pages,
    save_generated_message,
    list_generated_messages,
    update_status,
    delete_prospect,
    get_report,
    clear_all,
)
from site_fetcher import normalize_url, get_domain, research_website
from ai_service import analyze_prospect_with_ai, generate_outreach_email


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
        ["➕ Help", "🧹 Clear"],
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


def format_prospect_short(prospect) -> str:
    return (
        f"ID: {prospect['id']}\n"
        f"URL: {prospect['url']}\n"
        f"Domain: {prospect.get('domain') or '—'}\n"
        f"Status: {prospect.get('status') or '—'}\n"
        f"Relevance: {format_score(prospect.get('relevance_score'))}\n"
        f"Quality: {format_score(prospect.get('quality_score'))}\n"
        f"Risk: {prospect.get('risk_level') or '—'}"
    )


def format_prospect_detail(prospect, pages=None, messages=None) -> str:
    pages = pages or []
    messages = messages or []

    text = (
        f"Prospect #{prospect['id']}\n\n"
        f"URL: {prospect['url']}\n"
        f"Domain: {prospect.get('domain') or '—'}\n"
        f"Status: {prospect.get('status') or '—'}\n"
        f"Notes: {prospect.get('notes') or '—'}\n\n"
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

    if pages:
        text += "\nPages collected:\n"
        for page in pages[:8]:
            text += f"- {page['page_type']}: {page['url']}\n"

    if messages:
        text += f"\nGenerated messages: {len(messages)}"

    return text


def build_help_text() -> str:
    return (
        "AI Outreach Research Agent 🤖\n\n"
        "Команди:\n"
        "/add URL notes — додати сайт\n"
        "/prospects — список сайтів\n"
        "/view ID — деталі сайту\n"
        "/research ID — дослідити сайт\n"
        "/email ID — згенерувати перший email\n"
        "/followup ID — згенерувати follow-up\n"
        "/status ID status — змінити статус\n"
        "/delete ID — видалити сайт\n"
        "/report — звіт по статусах\n"
        "/clear — очистити всі prospects\n"
        "/myid — показати chat_id\n\n"
        "Статуси:\n"
        "new, researched, email_generated, contacted, replied, accepted, published, rejected\n\n"
        "Приклад:\n"
        "/add https://example.com target: guest post for pet niche"
    )


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

        lines = ["Твої prospects:\n"]

        for prospect in prospects:
            lines.append(
                f"{prospect['id']}. {prospect['domain'] or prospect['url']}\n"
                f"   Status: {prospect['status']}\n"
                f"   Relevance: {format_score(prospect.get('relevance_score'))}, "
                f"Risk: {prospect.get('risk_level') or '—'}"
            )

        await update.message.reply_text(
            "\n\n".join(lines),
            reply_markup=build_main_keyboard(),
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

        await update.message.reply_text(
            format_prospect_detail(prospect, pages, messages),
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

    await message.edit_text(
        "Research completed ✅\n\n"
        + format_prospect_detail(updated, pages),
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
        if not prospects:
            await update.message.reply_text("Prospects поки немає.")
            return True

        lines = ["Твої prospects:\n"]
        for prospect in prospects:
            lines.append(
                f"{prospect['id']}. {prospect['domain'] or prospect['url']}\n"
                f"   Status: {prospect['status']}"
            )

        await update.message.reply_text("\n\n".join(lines))
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

    if text == "➕ Help":
        await update.message.reply_text(build_help_text())
        return True

    if text == "🧹 Clear":
        await update.message.reply_text(
            "Щоб очистити всі prospects, напиши:\n/clear"
        )
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

    if await deny_if_not_allowed(update):
        return

    await query.answer()

    data = query.data

    try:
        parts = data.split(":")
        action = parts[0]
        prospect_id = int(parts[1])
    except Exception:
        await query.edit_message_text("Не зрозумів кнопку.")
        return

    fake_update = update
    fake_update.effective_message = query.message

    if action == "view":
        chat_id = query.message.chat_id
        prospect = get_prospect(prospect_id, chat_id)
        if not prospect:
            await query.edit_message_text("Prospect не знайдено.")
            return

        pages = list_prospect_pages(prospect_id)
        messages = list_generated_messages(prospect_id)

        await query.edit_message_text(
            format_prospect_detail(prospect, pages, messages),
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

    if action == "status":
        if len(parts) < 3:
            await query.edit_message_text("Не передано статус.")
            return

        status = parts[2]
        chat_id = query.message.chat_id
        updated = update_status(prospect_id, chat_id, status)

        if updated:
            await query.edit_message_text(
                f"Статус prospect {prospect_id} змінено на {status} ✅",
                reply_markup=build_prospect_keyboard(prospect_id),
            )
        else:
            await query.edit_message_text("Prospect не знайдено.")

        return


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
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Outreach Agent is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
