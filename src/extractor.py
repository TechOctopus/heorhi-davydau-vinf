import html
import re
from collections import Counter

from crawler import DATA, IGNORED_HTML, read_records, record_line, write_lines

ARTWORKS = DATA.parent / "artworks.tsv"
FIELDS = ["url", "title", "artist", "artist_wikipedia", "original_title", "date", "year_from", "year_to",
          "place", "style", "genre", "media", "location", "dimensions", "period", "series", "theme",
          "tags", "wikipedia", "description"]
# Every attribute in the artwork panel is written as a label and a value:
# <li class="dictionary-values"><s>Style:</s> <span><a href="...">Post-Impressionism</a></span></li>
LABELS = {"Original Title": "original_title", "Date": "date", "Style": "style", "Genre": "genre",
          "Media": "media", "Location": "location", "Dimensions": "dimensions", "Period": "period",
          "Series": "series", "Theme": "theme"}
LABELED = re.compile(r"<li\b[^>]*>\s*<s\b[^>]*>\s*([^<:]+?)\s*:\s*</s>(.*?)</li\s*>", re.I | re.S)
ARTICLE = re.compile(r"<article\b.*?</article\s*>", re.I | re.S)
HEADING = re.compile(r"<h3\b[^>]*>(.*?)</h3\s*>", re.I | re.S)
# <h5 itemprop="creator" ...><a href="/en/vincent-van-gogh">Vincent van Gogh</a>
#     <meta itemprop="sameAs" content="https://en.wikipedia.org/wiki/Vincent_van_Gogh" /></h5>
CREATOR = re.compile(r"itemprop\s*=\s*[\"']creator[\"'].*?<a\b[^>]*>(.*?)</a\s*>", re.I | re.S)
SAME_AS = re.compile(r"itemprop\s*=\s*[\"']sameAs[\"']\s+content\s*=\s*[\"']([^\"']+)", re.I)
# <s>Wikipedia:</s> <a class="truncate external" href="https://en.wikipedia.org/wiki/The_Starry_Night">
WIKIPEDIA = re.compile(r"<s\b[^>]*>\s*Wikipedia\s*:\s*</s>\s*<a\b[^>]*?\s+href\s*=\s*[\"']([^\"']+)", re.I)
DESCRIPTION = re.compile(r"<p\b[^>]*\bitemprop\s*=\s*[\"']description[\"'][^>]*>(.*?)</p\s*>", re.I | re.S)
TAG_LINK = re.compile(r"<a\b[^>]*?\s+href\s*=\s*[\"']/en/tag/[^\"']*[\"'][^>]*>(.*?)</a\s*>", re.I | re.S)
YEAR = re.compile(r"\b\d{3,4}\b")
LINE_BREAK = re.compile(r"<br\b[^>]*>", re.I)
MARKUP = re.compile(r"<[^>]+>")


def clean(fragment):
    """HTML fragment -> one line of text: tags are removed (<br> becomes a space), entities decoded."""
    return " ".join(html.unescape(MARKUP.sub("", LINE_BREAK.sub(" ", fragment))).split())


def first(pattern, text):
    match = pattern.search(text)
    return clean(match[1]) if match else ""


def extract_artwork(document, url):
    """One record from an artwork page; fields missing on the page stay empty."""
    document = IGNORED_HTML.sub("", document)
    match = ARTICLE.search(document)
    article = match[0] if match else ""
    record = dict.fromkeys(FIELDS, "")
    record.update(url=url, title=first(HEADING, article), artist=first(CREATOR, article),
                  artist_wikipedia=first(SAME_AS, article), wikipedia=first(WIKIPEDIA, document),
                  description=first(DESCRIPTION, document),
                  tags=", ".join(clean(tag) for tag in TAG_LINK.findall(document)))
    for label, value in LABELED.findall(article):
        if label in LABELS:
            record[LABELS[label]] = clean(value)
    # "c.1610 - c.1612; Antwerp, Belgium": the place follows the first semicolon.
    date, _, place = record["date"].partition(";")
    years = YEAR.findall(date)
    record.update(date=date.strip(), place=place.strip(),
                  year_from=years[0] if years else "", year_to=years[-1] if years else "")
    return record


def extract(output=DATA, target=ARTWORKS):
    pages = {}
    for row in read_records(output):
        # A redirect can lead to a page that was also saved under its own URL.
        if row["kind"] == "artwork" and row["file"]:
            pages.setdefault(row["final_url"], row)
    records = [extract_artwork((output / row["file"]).read_bytes().decode(row["encoding"], errors="replace"), url)
               for url, row in pages.items()]
    write_lines(target, ["\t".join(FIELDS)] + [record_line(record, FIELDS) for record in records])
    filled = Counter(field for record in records for field in FIELDS if record[field])
    return {"artworks": len(records), "filled_fields": {field: filled[field] for field in FIELDS}}
