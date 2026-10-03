"""Read the five open remote-job boards and list new jobs open to the Philippines.

  py -X utf8 feeds.py            fetch, write .hunt/inbox.json, print one line per job
  py -X utf8 feeds.py show 3 7   print the posts of inbox items 3 and 7

Standard library only. One Remotive request per run: they ask for about 4 a day.
"""
import datetime as dt
import email.utils
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET  # trusted feed; Python's expat rejects external entities and entity bombs
from pathlib import Path

HERE = Path(__file__).resolve().parent
INBOX = HERE / ".hunt" / "inbox.json"
JOBS = HERE / "jobs.json"
UA = {"User-Agent": "job-hunt/1.0 (personal job search)"}

FIT = re.compile(
    r"\b(ai|ml|llm|gpt|genai|machine learning|automation|full[- ]?stack|back[- ]?end|front[- ]?end|software|"
    r"developer|engineer|programmer|python|node(\.js)?|react|next\.?js|typescript|javascript|fastapi|supabase|expo|mobile)\b",
    re.I,
)
OPEN = re.compile(r"worldwide|anywhere|global|philippines|\basia\b|apac|^remote$", re.I)
LOCKED = re.compile(
    r"remote\s*[(\-–:,/]?\s*(us|usa|u\.s\.?|united states|europe|eu|emea|uk|canada|north america|americas|latam)\b", re.I
)


def text(fragment):
    """HTML to plain text, keeping paragraph breaks."""
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|<p[^>]*>", "\n", fragment or "")
    plain = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    return re.sub(r"\n\s*\n+", "\n\n", plain).strip()


def open_to_ph(location):
    location = (location or "").strip()
    return not location or bool(OPEN.search(location))


def job(source, url, title, company, posted, post, location="", pay=None):
    return {"source": source, "url": url, "title": title.strip(), "company": company.strip() or "unknown",
            "pay": pay, "posted": posted, "post": post, "location": location}


def day(epoch):
    return dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc).date().isoformat()


def parse_remoteok(raw):
    jobs = []
    for item in json.loads(raw)[1:]:  # item 0 is the legal notice
        low, high = int(item.get("salary_min") or 0), int(item.get("salary_max") or 0)
        pay = f"${low:,}-${high:,}/year" if high else None
        jobs.append(job("remoteok", item["url"], item["position"], item["company"], item["date"][:10],
                        text(item.get("description")), item.get("location") or "", pay))
    return jobs


def parse_wwr(raw):
    jobs = []
    for item in ET.fromstring(raw).iter("item"):
        company, sep, title = (item.findtext("title") or "").partition(": ")
        if not sep:
            company, title = "", company
        posted = email.utils.parsedate_to_datetime(item.findtext("pubDate")).date().isoformat()
        jobs.append(job("wwr", item.findtext("link"), title, company, posted,
                        text(item.findtext("description")), item.findtext("region") or ""))
    return jobs


def parse_himalayas(raw):
    jobs = []
    for item in json.loads(raw)["jobs"]:
        low, high = item.get("minSalary"), item.get("maxSalary")
        pay = (f"{item.get('currency') or 'USD'} {int(low):,}-{int(high):,}/{item.get('salaryPeriod') or 'year'}"
               if low and high else None)
        jobs.append(job("himalayas", item["guid"], item["title"], item["companyName"], day(item["pubDate"]),
                        text(item.get("description")), ", ".join(item.get("locationRestrictions") or []), pay))
    return jobs


def parse_remotive(raw):
    jobs = []
    for item in json.loads(raw)["jobs"]:
        if "software" not in (item.get("category") or "").lower():
            continue
        jobs.append(job("remotive", item["url"], item["title"], item["company_name"], item["publication_date"][:10],
                        text(item.get("description")), item.get("candidate_required_location") or "",
                        item.get("salary") or None))
    return jobs


def parse_hn(raw):
    jobs = []
    for item in json.loads(raw)["children"]:
        body = text(item.get("text"))
        first = body.split("\n", 1)[0]
        if not body or "remote" not in first.lower() or LOCKED.search(first):
            continue
        cells = [cell.strip() for cell in first.split("|")]
        title = cells[1] if len(cells) > 1 else first[:80]
        # Location stays empty: the country lock was already checked on the first line above.
        jobs.append(job("hn", f"https://news.ycombinator.com/item?id={item['id']}", title, cells[0][:80],
                        day(item["created_at_i"]), body))
    return jobs


def select(items, since, seen):
    """Keep jobs posted on or after since, with a fitting title, open to the Philippines and not seen yet."""
    kept = []
    for item in items:
        if item["url"] in seen or item["posted"] < since or not FIT.search(item["title"]) or not open_to_ph(item["location"]):
            continue
        seen.add(item["url"])
        kept.append(item)
    return kept


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as response:
        return response.read().decode("utf-8")


def hn_thread():
    for item_id in json.loads(get("https://hacker-news.firebaseio.com/v0/user/whoishiring.json"))["submitted"][:6]:
        item = json.loads(get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"))
        if (item.get("title") or "").startswith("Ask HN: Who is hiring?"):
            return get(f"https://hn.algolia.com/api/v1/items/{item_id}")
    raise RuntimeError("no Who is hiring thread in the last 6 posts")


HIMALAYAS = "https://himalayas.app/jobs/api/search?country=Philippines&sort=recent&q="
WWR = "https://weworkremotely.com/categories/remote-{}-programming-jobs.rss"
FEEDS = [
    ("remoteok", lambda: parse_remoteok(get("https://remoteok.com/api"))),
    ("wwr", lambda: parse_wwr(get(WWR.format("full-stack"))) + parse_wwr(get(WWR.format("back-end")))),
    ("himalayas", lambda: [j for q in ("ai%20engineer", "full%20stack", "automation") for j in parse_himalayas(get(HIMALAYAS + q))]),
    ("remotive", lambda: parse_remotive(get("https://remotive.com/api/remote-jobs?category=software-dev"))),
    ("hn", lambda: parse_hn(hn_thread())),
]


def collect(days, known):
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    found, failed, seen = [], [], set(known)
    for name, fetch in FEEDS:
        try:
            found += select(fetch(), since, seen)
        except Exception as error:  # one bad feed must not stop the others
            failed.append(f"{name}: {error}")
    return found, failed


def main(argv):
    if argv[:1] == ["show"]:
        inbox = {item["n"]: item for item in json.loads(INBOX.read_text(encoding="utf-8"))}
        for n in argv[1:]:
            item = inbox[int(n)]
            print(f"--- {n} | {item['title']} | {item['company']} | {item['location'] or 'no location limit'} | {item['url']}")
            print(item["post"][:4000], end="\n\n")
        return 0
    known = [job["url"] for job in json.loads(JOBS.read_text(encoding="utf-8"))["jobs"]] if JOBS.exists() else []
    days = 3 if known else 7
    found, failed = collect(days, known)
    for n, item in enumerate(found, 1):
        item["n"] = n
    INBOX.parent.mkdir(exist_ok=True)
    INBOX.write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    for item in found:
        print(f"{item['n']:>3} | {item['source']} | {item['title'][:60]} | {item['company'][:30]} | "
              f"{item['location'][:30] or '-'} | {item['pay'] or '-'} | {item['posted']}")
    print(f"{len(found)} new in the last {days} days. Failed: {'; '.join(failed) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
