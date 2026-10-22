import hashlib
import html
import json
import logging
import os
import re
import time
from collections import Counter, deque
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


def write_lines(path, lines):
    atomic_write(path, "".join(line + "\n" for line in lines).encode())


def save_state(output, state):
    atomic_write(output / "state.json", json.dumps(state, ensure_ascii=False, indent=2).encode())


def append_lines(path, lines):
    """Append whole lines and force them to disk; a crash can cut off only the last line."""
    if not lines:
        return
    with path.open("a", encoding="utf-8") as file:
        file.writelines(line + "\n" for line in lines)
        file.flush()
        os.fsync(file.fileno())


def read_lines(path):
    """Read complete lines only; text after the last newline is an interrupted append."""
    if not path.exists():
        return []
    data = path.read_bytes()
    return data[:data.rfind(b"\n") + 1].decode("utf-8").splitlines()


def drop_partial_line(path):
    """Only the crawler (the single writer) repairs a log before appending to it again."""
    if path.exists():
        data = path.read_bytes()
        end = data.rfind(b"\n") + 1
        if end != len(data):
            with path.open("r+b") as file:
                file.truncate(end)


def record_line(row):
    # TSV cells cannot contain tabs or line breaks, so whitespace runs become one space.
    return "\t".join(" ".join(str(row[field]).split()) for field in FIELDS)


def read_records(output):
    records = [dict(zip(FIELDS, line.split("\t"))) for line in read_lines(output / "pages.tsv")[1:]]
    for row in records:
        row["status"] = int(row["status"] or 0)
        row["bytes"] = int(row["bytes"] or 0)
    return records


def read_frontier(output):
    return read_lines(output / "frontier.txt")


def pending_urls(frontier, records):
    processed = {row["url"] for row in records}
    return [url for url in frontier if url not in processed]


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


def artist_list_url(artist):
    return f"{BASE_URL}/en/{artist}/all-works/text-list"


def load_state(output, artists):
    checkpoint = output / "state.json"
    if not checkpoint.exists():
        write_lines(output / "pages.tsv", ["\t".join(FIELDS)])
        write_lines(output / "frontier.txt", [artist_list_url(artist) for artist in artists])
        state = {"created_at": now(), "artists": artists}
        save_state(output, state)
        return state
    state = json.loads(checkpoint.read_text())
    if state["artists"] != artists:
        raise ValueError("Use the same --artist values to resume, or choose a new --output directory.")
    return state


def summarize(output):
    """pages.tsv and frontier.txt are authoritative; summary.json can always be regenerated."""
    records = read_records(output)
    downloaded = [row for row in records if row["file"]]
    summary = {
        "saved_pages": len(downloaded),
        "artwork_pages": sum(row["kind"] == "artwork" for row in downloaded),
        "list_pages": sum(row["kind"] == "list" for row in downloaded),
        "html_bytes": sum(row["bytes"] for row in downloaded),
        "pending_urls": len(pending_urls(read_frontier(output), records)),
        "skipped_or_failed": len(records) - len(downloaded),
        "http_statuses": dict(Counter(str(row["status"]) for row in records)),
        "updated_at": records[-1]["fetched_at"] if records else "",
    }
    atomic_write(output / "summary.json", json.dumps(summary, indent=2).encode())
    return summary


def fetch_page(client, robots, url, artists):
    """Fetch one queued URL and follow only in-scope redirects.
    Returns the metadata row, the raw body, and the decoded HTML (body is None if skipped)."""
    final_url, status, headers, body, error = url, 0, {}, b"", ""
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
    if error:
        return row, None, None
    encoding = requests.utils.get_encoding_from_headers(headers) or "utf-8"
    document = body.decode(encoding, errors="replace")
    title = page_title(document)
    if not title or any(marker in title.lower() for marker in ("just a moment", "access denied", "captcha")):
        raise CrawlStopped(f"Unexpected HTML at {final_url}: {title!r}")
    row.update(title=title, encoding=encoding, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
               file="raw/" + hashlib.sha256(url.encode()).hexdigest() + ".html")
    return row, body, document


def crawl(output, artists, max_pages, delay=2.0, client=None):
    output.mkdir(parents=True, exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)
    state = load_state(output, artists)
    for name in ("pages.tsv", "frontier.txt"):
        drop_partial_line(output / name)
    records = read_records(output)
    frontier = read_frontier(output)
    pending = deque(pending_urls(frontier, records))
    known = set(frontier)
    saved = sum(bool(row["file"]) for row in records)
    del records, frontier
    if saved >= max_pages or not pending:
        return summarize(output)
    client = client or PoliteClient(delay=delay)
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
        save_state(output, state)
        while pending and saved < max_pages:
            url = pending[0]  # Remove only after its record has been appended.
            row, body, document = fetch_page(client, robots, url, artists)
            if body is not None:
                atomic_write(output / row["file"], body)
                links = [link for link in extract_links(document, row["final_url"], artists) if link not in known]
                # Links go to disk before the record: a crash may repeat a page but never loses its links.
                append_lines(output / "frontier.txt", links)
                known.update(links)
                pending.extend(links)
                saved += 1
                LOG.info("Saved %s/%s: %s (%s bytes)", saved, max_pages, row["title"], row["bytes"])
            else:
                LOG.warning("Skipped %s: %s", url, row["error"])
            append_lines(output / "pages.tsv", [record_line(row)])
            pending.popleft()
    finally:
        client.session.close()
        summary = summarize(output)
    return summary
