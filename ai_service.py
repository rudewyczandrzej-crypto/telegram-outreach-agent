import os
import json

from groq import Groq


MODEL_NAME = "llama-3.3-70b-versatile"


def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError("GROQ_API_KEY не знайдено у Railway Variables")

    return Groq(api_key=api_key)


def clean_json_text(text: str) -> str:
    text = text.strip()

    if text.startswith("```json"):
        text = text.replace("```json", "", 1).strip()

    if text.startswith("```"):
        text = text.replace("```", "", 1).strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    return text


def build_research_context(prospect: dict, website_data: dict) -> str:
    pages_summary = []

    for page in website_data.get("pages", []):
        pages_summary.append(
            {
                "url": page.get("url"),
                "page_type": page.get("page_type"),
                "title": page.get("title"),
                "meta_description": page.get("meta_description"),
                "h1": page.get("h1"),
                "h2": page.get("h2", [])[:8],
                "text_excerpt": page.get("text_excerpt"),
                "emails_found": page.get("emails_found", []),
            }
        )

    return json.dumps(
        {
            "prospect": {
                "url": prospect.get("url"),
                "domain": prospect.get("domain"),
                "notes": prospect.get("notes"),
            },
            "website_data": {
                "domain": website_data.get("domain"),
                "all_emails": website_data.get("all_emails", []),
                "contact_page": website_data.get("contact_page"),
                "has_blog": website_data.get("has_blog"),
                "has_write_for_us": website_data.get("has_write_for_us"),
                "pages": pages_summary,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def analyze_prospect_with_ai(prospect: dict, website_data: dict) -> dict:
    context = build_research_context(prospect, website_data)

    system_prompt = """
You are an AI outreach research assistant for SEO link building and digital PR.

Your task:
Analyze a website prospect and return structured JSON for outreach qualification.

Rules:
1. Return only valid JSON.
2. Do not include markdown outside JSON.
3. Be practical and realistic.
4. If data is missing, use null or reasonable cautious inference.
5. Scores must be integers from 1 to 10.
6. risk_level must be one of: low, medium, high.
7. Mention if the site looks unsuitable for outreach.
8. Do not invent exact metrics like DR, traffic, or backlinks.
9. Focus on topical relevance, content quality, contact availability, and outreach angle.

JSON format:
{
  "site_title": "string or null",
  "meta_description": "string or null",
  "language": "English | Polish | Ukrainian | German | French | Spanish | Other | Unknown",
  "niche": "short niche label",
  "contact_email": "best email or null",
  "contact_page": "contact page URL or null",
  "has_blog": true or false,
  "has_write_for_us": true or false,
  "relevance_score": 1-10,
  "quality_score": 1-10,
  "risk_level": "low | medium | high",
  "outreach_angle": "short practical outreach angle",
  "summary": "short summary for outreach specialist"
}
"""

    client = get_groq_client()

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
        temperature=0.2,
    )

    raw_text = response.choices[0].message.content
    raw_text = clean_json_text(raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "site_title": None,
            "meta_description": None,
            "language": "Unknown",
            "niche": None,
            "contact_email": None,
            "contact_page": None,
            "has_blog": bool(website_data.get("has_blog")),
            "has_write_for_us": bool(website_data.get("has_write_for_us")),
            "relevance_score": None,
            "quality_score": None,
            "risk_level": "medium",
            "outreach_angle": None,
            "summary": f"AI returned invalid JSON: {raw_text[:500]}",
        }


def generate_outreach_email(prospect: dict, message_type: str = "first_email") -> dict:
    system_prompt = """
You are an outreach specialist for SEO link building.

Generate a personalized outreach email based on the prospect data.

Rules:
1. Return only valid JSON.
2. Do not use markdown outside JSON.
3. Do not mention fake metrics.
4. Do not overpromise.
5. Keep it natural, short, and professional.
6. Use English unless the prospect language clearly suggests another language.
7. Use placeholders if recipient name is unknown.
8. Avoid spammy wording.
9. For first_email: propose a relevant collaboration angle.
10. For followup: write a polite follow-up referencing the previous message.

JSON format:
{
  "subject": "email subject",
  "body": "email body"
}
"""

    user_context = json.dumps(
        {
            "message_type": message_type,
            "prospect": {
                "url": prospect.get("url"),
                "domain": prospect.get("domain"),
                "notes": prospect.get("notes"),
                "site_title": prospect.get("site_title"),
                "meta_description": prospect.get("meta_description"),
                "language": prospect.get("language"),
                "niche": prospect.get("niche"),
                "contact_email": prospect.get("contact_email"),
                "has_blog": prospect.get("has_blog"),
                "has_write_for_us": prospect.get("has_write_for_us"),
                "relevance_score": prospect.get("relevance_score"),
                "quality_score": prospect.get("quality_score"),
                "risk_level": prospect.get("risk_level"),
                "outreach_angle": prospect.get("outreach_angle"),
                "summary": prospect.get("summary"),
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    client = get_groq_client()

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_context},
        ],
        temperature=0.5,
    )

    raw_text = response.choices[0].message.content
    raw_text = clean_json_text(raw_text)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "subject": "Collaboration idea",
            "body": raw_text,
        }
