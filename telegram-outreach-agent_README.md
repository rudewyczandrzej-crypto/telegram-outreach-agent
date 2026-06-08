# AI Outreach Research Agent

Telegram-based AI agent for SEO outreach, link building, and prospect research.

## What problem it solves

Outreach specialists spend a lot of time collecting websites, checking relevance, finding contacts, generating emails, tracking statuses, and preparing reports.  
This agent works like a small AI-powered outreach CRM.

## Main features

- Add website prospects
- Lightweight website research
- Extracts:
  - domain
  - title
  - meta description
  - headings
  - contact pages
  - emails
  - blog / write-for-us signals
- AI relevance score
- AI quality score
- Risk level
- Outreach angle generation
- Personalized outreach email generation
- Follow-up generation
- Subject line ideas
- Manual SEO fields:
  - DR
  - traffic
  - price
  - contact person
  - email
  - niche
- Status tracking:
  - new
  - researched
  - email_generated
  - contacted
  - replied
  - accepted
  - published
  - rejected
- Notes history
- Published link tracking
- CSV export
- PostgreSQL database
- Optional private access with `ALLOWED_CHAT_IDS`

## Example use case

User adds a prospect:

```text
/add https://example.com target: guest post for pet niche
```

Then the agent can research the website, extract contact information, score the prospect, and generate a personalized outreach email.

## Commands

```text
/start — start the bot
/add URL notes — add prospect
/prospects — list prospects
/view ID — show prospect details
/research ID — research website
/email ID — generate outreach email
/followup ID — generate follow-up
/subjects ID — generate subject line ideas
/contact ID — show contact data
/set ID field value — set manual SEO field
/best — show best prospects
/search query — search prospects
/note ID text — add note
/published ID published_url anchor target_url — save published link
/status ID status — update status
/export — export CSV
/delete ID — delete prospect
/clear — clear all data
/myid — show Telegram chat ID
```

## Example manual fields

```text
/set 4 dr 55
/set 4 traffic 12000
/set 4 price 80$
/set 4 contact Anna
/set 4 email editor@example.com
```

## Tech stack

- Python
- python-telegram-bot
- Groq API
- PostgreSQL
- requests
- BeautifulSoup
- tldextract
- Railway-compatible deployment

## Environment variables

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GROQ_API_KEY=your_groq_api_key
DATABASE_URL=your_postgres_database_url
ALLOWED_CHAT_IDS=
```

## Important note about DR and traffic

The agent does not invent DR or traffic.  
These metrics require external SEO APIs such as Ahrefs, Semrush, or Similarweb.  
In this MVP, DR and traffic are manual fields.

## How to run locally

```bash
pip install -r requirements.txt
python main.py
```

## How to deploy

The project includes a worker-style deployment setup:

```text
worker: python main.py
```

## Portfolio value

This project demonstrates:

- AI-powered website research
- lead/prospect CRM logic
- contact extraction
- outreach automation
- email and follow-up generation
- CSV reporting
- PostgreSQL data modeling
- Telegram bot UI with buttons
- practical SEO / digital marketing automation
