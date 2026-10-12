import csv
import hashlib
import html
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

BASE_URL = "https://www.wikiart.org"
USER_AGENT = (
    "VINF-PaintingsCrawler/0.1 "
    "(+https://github.com/TechOctopus/heorhi-davydau-vinf; educational project)"
)
DEFAULT_ARTISTS = ["vincent-van-gogh", "claude-monet", "gustav-klimt"]
FIELDS = ["url", "final_url", "fetched_at", "status", "kind", "title",
          "content_type", "encoding", "bytes", "sha256", "file", "error"]
HREF = re.compile(r"<a\b[^>]*?\s+href\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)
IGNORED_HTML = re.compile(r"<!--.*?-->|<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Artwork slugs may hold percent-encoded letters (p%C3%A8re-tanguy) and underscores (not_detected_212152).
ARTWORK_SLUG = re.compile(r"(?:[a-z0-9_-]|%[0-9A-Fa-f]{2})+")
LOG = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_url(link, base, artists):
    """Keep only English artwork pages and text lists for the selected artists."""
    try:
        url = urlsplit(urljoin(base, html.unescape(link).strip()))
        if (url.scheme not in {"http", "https"}
                or url.hostname not in {"wikiart.org", "www.wikiart.org"}
                or url.username or url.password or url.port or url.query):
            return None
    except ValueError:
        return None
    parts = url.path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "en" or parts[1] not in artists:
        return None
    is_list = parts[2:] == ["all-works", "text-list"]
    is_artwork = len(parts) == 3 and parts[2] != "all-works" and ARTWORK_SLUG.fullmatch(parts[2])
    if not (is_list or is_artwork):
        return None
    return BASE_URL + "/" + "/".join(parts)


def extract_links(document, base, artists):
    """Regex extraction is a course requirement; preserve order and remove duplicates."""
    links = {}
    for match in HREF.finditer(IGNORED_HTML.sub("", document)):
        link = next(value for value in match.groups() if value is not None)
        normalized = normalize_url(link, base, artists)
        if normalized:
            links[normalized] = None
    return list(links)


def page_title(document):
    match = TITLE.search(document)
    return " ".join(html.unescape(match[1]).split()) if match else ""


def atomic_write(path, content):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def save_state(output, state):
    atomic_write(output / "state.json", json.dumps(state, ensure_ascii=False, indent=2).encode())


def retry_after(value):
    """Retry-After can be seconds or an HTTP date."""
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


class CrawlStopped(Exception):
    """A temporary/site-level problem: keep the current URL queued for a later run."""


class PoliteClient:
    def __init__(self, delay=2.0, timeout=(10, 30), attempts=3):
        self.delay = delay
        self.timeout = timeout
        self.attempts = attempts
        self.last_request = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            "Accept-Language": "en",
        })

    def get(self, url):
        for attempt in range(self.attempts):
            if self.last_request is not None:
                time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            wait = 2 ** (attempt + 1)
            try:
                # Redirects are handled by crawl() so every target is checked first.
                with self.session.get(url, timeout=self.timeout, allow_redirects=False, stream=True) as response:
                    if response.status_code in {429, 500, 502, 503, 504}:
                        wait = max(wait, retry_after(response.headers.get("Retry-After")))
                        reason = f"HTTP {response.status_code}"
                    else:
                        chunks = []
                        size = 0
                        for chunk in response.iter_content(64 * 1024):
                            size += len(chunk)
                            if size > 5_000_000:
                                raise CrawlStopped(f"Response exceeds 5 MB: {url}")
                            chunks.append(chunk)
                        return response.status_code, response.headers, b"".join(chunks)
            except requests.RequestException as error:
                reason = str(error)
            if attempt + 1 == self.attempts or wait > 60:
                raise CrawlStopped(f"{url}: {reason}; retry later (wait at least {wait:g}s)")
            LOG.warning("%s; retry %s/%s in %.1fs", reason, attempt + 2, self.attempts, wait)
            time.sleep(wait)
        raise AssertionError("Unreachable")


def load_state(output, artists):
    checkpoint = output / "state.json"
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state["artists"] != artists:
            raise ValueError("Use the same --artist values to resume, or choose a new --output directory.")
        return state
    return {
        "version": 1, "created_at": now(), "artists": artists,
        "pending": [f"{BASE_URL}/en/{artist}/all-works/text-list" for artist in artists],
        "records": [],
    }


def export_results(output, state):
    """The checkpoint is authoritative; TSV and summary can always be regenerated."""
    with (output / "pages.tsv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(state["records"])
    downloaded = [row for row in state["records"] if row["file"]]
    summary = {
        "saved_pages": len(downloaded),
        "artwork_pages": sum(row["kind"] == "artwork" for row in downloaded),
        "list_pages": sum(row["kind"] == "list" for row in downloaded),
        "html_bytes": sum(row["bytes"] for row in downloaded),
        "pending_urls": len(state["pending"]),
        "skipped_or_failed": len(state["records"]) - len(downloaded),
        "http_statuses": dict(Counter(str(row["status"]) for row in state["records"])),
        "updated_at": state.get("updated_at", state["created_at"]),
    }
    atomic_write(output / "summary.json", json.dumps(summary, indent=2).encode())
    return summary


def crawl(output, artists, max_pages, delay=2.0, client=None):
    output.mkdir(parents=True, exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)
    state = load_state(output, artists)
    saved = sum(bool(row["file"]) for row in state["records"])
    if saved >= max_pages or not state["pending"]:
        return export_results(output, state)
    client = client or PoliteClient(delay=delay)
    save_state(output, state)
    try:
        status, headers, body = client.get(BASE_URL + "/robots.txt")
        if status != 200 or b"<html" in body.lower():
            raise CrawlStopped(f"Cannot verify robots.txt (HTTP {status})")
        atomic_write(output / "robots.txt", body)
        robots = RobotFileParser()
        robots.parse(body.decode("utf-8-sig").splitlines())
        client.delay = max(client.delay, robots.crawl_delay(USER_AGENT) or 0)
        rate = robots.request_rate(USER_AGENT)
        if rate and rate.requests:
            client.delay = max(client.delay, rate.seconds / rate.requests)
        state["settings"] = {
            "user_agent": USER_AGENT, "delay_seconds": client.delay,
            "connect_timeout_seconds": 10, "read_timeout_seconds": 30,
            "max_attempts": 3, "max_response_bytes": 5_000_000,
            "robots_checked_at": now(),
        }
        known = set(state["pending"]) | {row["url"] for row in state["records"]}
        while state["pending"] and saved < max_pages:
            url = state["pending"][0]  # Remove only after the page has been processed.
            final_url = url
            status, headers, body = 0, {}, b""
            error = ""
            for redirect in range(6):
                if not robots.can_fetch(USER_AGENT, final_url):
                    error = "Disallowed by robots.txt"
                    break
                status, headers, body = client.get(final_url)
                if status not in {301, 302, 303, 307, 308}:
                    break
                target = normalize_url(headers.get("Location", ""), final_url, artists)
                if not target or redirect == 5:
                    error = "Redirect outside crawl scope or too many redirects"
                    break
                final_url = target
            if status in {401, 403}:
                raise CrawlStopped(f"HTTP {status} at {final_url}; current URL remains queued")
            content_type = headers.get("Content-Type", "").split(";")[0].strip().lower()
            if not error and (status != 200 or content_type not in {"text/html", "application/xhtml+xml"}):
                error = f"Not an HTML success (HTTP {status}, {content_type})"
            row = dict.fromkeys(FIELDS, "")
            row.update(url=url, final_url=final_url, fetched_at=now(), status=status,
                       kind="list" if final_url.endswith("/all-works/text-list") else "artwork",
                       content_type=content_type, bytes=0, error=error)
            if not error:
                encoding = requests.utils.get_encoding_from_headers(headers) or "utf-8"
                document = body.decode(encoding, errors="replace")
                title = page_title(document)
                if not title or any(marker in title.lower() for marker in ("just a moment", "access denied", "captcha")):
                    raise CrawlStopped(f"Unexpected HTML at {final_url}: {title!r}")
                filename = "raw/" + hashlib.sha256(url.encode()).hexdigest() + ".html"
                atomic_write(output / filename, body)
                row.update(title=title, encoding=encoding, bytes=len(body),
                           sha256=hashlib.sha256(body).hexdigest(), file=filename)
                for link in extract_links(document, final_url, artists):
                    if link not in known:
                        state["pending"].append(link)
                        known.add(link)
                saved += 1
                LOG.info("Saved %s/%s: %s (%s bytes)", saved, max_pages, title, len(body))
            else:
                LOG.warning("Skipped %s: %s", url, error)
            state["records"].append(row)
            state["pending"].pop(0)
            state["updated_at"] = now()
            save_state(output, state)
    finally:
        save_state(output, state)
        export_results(output, state)
        client.session.close()
    return export_results(output, state)
