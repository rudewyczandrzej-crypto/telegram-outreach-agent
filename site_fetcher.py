import re
from urllib.parse import urljoin, urlparse

import requests
import tldextract
from bs4 import BeautifulSoup


IMPORTANT_KEYWORDS = [
    "about",
    "contact",
    "write-for-us",
    "write_for_us",
    "guest-post",
    "guestpost",
    "contribute",
    "advertise",
    "blog",
    "editorial",
    "submit",
]


BLOCKED_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
    ".zip",
    ".rar",
    ".mp4",
    ".mp3",
    ".avi",
    ".mov",
)


def normalize_url(url: str) -> str:
    url = url.strip()

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    return url


def get_domain(url: str) -> str:
    parsed = tldextract.extract(url)
    if parsed.suffix:
        return f"{parsed.domain}.{parsed.suffix}"
    return urlparse(url).netloc


def is_same_domain(url: str, base_domain: str) -> bool:
    return get_domain(url) == base_domain


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    return text.strip()


def extract_emails(text: str) -> list[str]:
    emails = re.findall(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        text or "",
    )

    cleaned = []
    for email in emails:
        email = email.strip().lower()
        if email not in cleaned:
            cleaned.append(email)

    return cleaned[:10]


def fetch_html(url: str) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; OutreachResearchBot/1.0; "
            "+https://example.com/bot)"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=12)
        content_type = response.headers.get("content-type", "").lower()

        if response.status_code >= 400:
            return None

        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return None

        return response.text
    except Exception:
        return None


def parse_page(url: str, html: str, page_type: str = "page") -> dict:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = clean_text(soup.title.string if soup.title else "")

    meta_description = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_description = clean_text(meta_tag.get("content"))

    h1_tag = soup.find("h1")
    h1 = clean_text(h1_tag.get_text(" ", strip=True)) if h1_tag else ""

    h2_list = [
        clean_text(h.get_text(" ", strip=True))
        for h in soup.find_all("h2")[:10]
    ]

    body_text = clean_text(soup.get_text(" ", strip=True))
    emails = extract_emails(body_text + " " + html)

    links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        label = clean_text(a.get_text(" ", strip=True))
        absolute_url = urljoin(url, href)

        if absolute_url.lower().endswith(BLOCKED_EXTENSIONS):
            continue

        links.append(
            {
                "url": absolute_url,
                "label": label,
            }
        )

    return {
        "url": url,
        "page_type": page_type,
        "title": title,
        "meta_description": meta_description,
        "h1": h1,
        "h2": h2_list,
        "text": body_text[:6000],
        "text_excerpt": body_text[:1000],
        "emails_found": emails,
        "links": links,
    }


def classify_link(url: str, label: str) -> str | None:
    check = (url + " " + label).lower()

    if any(word in check for word in ["contact", "kontakt"]):
        return "contact"

    if any(word in check for word in ["about", "o-nas", "about-us"]):
        return "about"

    if any(word in check for word in ["write-for-us", "guest-post", "contribute", "submit"]):
        return "write_for_us"

    if "advertise" in check or "media-kit" in check:
        return "advertise"

    if "blog" in check or "articles" in check:
        return "blog"

    return None


def select_important_links(home_page: dict, base_domain: str, limit: int = 8) -> list[dict]:
    selected = []
    seen_urls = set()

    for link in home_page.get("links", []):
        link_url = link["url"]
        label = link.get("label", "")

        parsed = urlparse(link_url)

        if parsed.scheme not in ["http", "https"]:
            continue

        if not is_same_domain(link_url, base_domain):
            continue

        if link_url in seen_urls:
            continue

        page_type = classify_link(link_url, label)
        if not page_type:
            continue

        selected.append(
            {
                "url": link_url,
                "page_type": page_type,
            }
        )
        seen_urls.add(link_url)

        if len(selected) >= limit:
            break

    return selected


def research_website(url: str) -> dict:
    normalized_url = normalize_url(url)
    domain = get_domain(normalized_url)

    home_html = fetch_html(normalized_url)

    if not home_html:
        return {
            "url": normalized_url,
            "domain": domain,
            "success": False,
            "error": "Не зміг завантажити головну сторінку.",
            "pages": [],
            "all_emails": [],
            "contact_page": None,
            "has_blog": False,
            "has_write_for_us": False,
        }

    home_page = parse_page(normalized_url, home_html, page_type="home")
    important_links = select_important_links(home_page, domain)

    pages = [home_page]
    seen = {normalized_url}

    for item in important_links:
        page_url = item["url"]

        if page_url in seen:
            continue

        html = fetch_html(page_url)
        if not html:
            continue

        page = parse_page(page_url, html, page_type=item["page_type"])
        pages.append(page)
        seen.add(page_url)

        if len(pages) >= 9:
            break

    all_emails = []
    contact_page = None
    has_blog = False
    has_write_for_us = False

    for page in pages:
        for email in page.get("emails_found", []):
            if email not in all_emails:
                all_emails.append(email)

        if page.get("page_type") == "contact" and not contact_page:
            contact_page = page.get("url")

        if page.get("page_type") == "blog":
            has_blog = True

        if page.get("page_type") == "write_for_us":
            has_write_for_us = True

    return {
        "url": normalized_url,
        "domain": domain,
        "success": True,
        "error": None,
        "pages": pages,
        "all_emails": all_emails[:10],
        "contact_page": contact_page,
        "has_blog": has_blog,
        "has_write_for_us": has_write_for_us,
    }
