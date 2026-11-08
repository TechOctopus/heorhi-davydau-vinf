import html
import re
from urllib.parse import unquote

FIELDS = ["title", "infobox", "description", "birth_date", "birth_year", "birth_place", "death_date",
          "death_year", "death_place", "movement", "location", "years_active", "categories", "abstract",
          "disambiguation"]
# Infobox parameters of artists, artworks, museums and art movements -> our fields.
PARAMS = {"birth_date": "birth_date", "birth_place": "birth_place", "death_date": "death_date",
          "death_place": "death_place", "movement": "movement", "location": "location", "museum": "location",
          "years_active": "years_active", "yearsactive": "years_active"}

# <text bytes="286264" xml:space="preserve">{{Short description|American artist ...}} ...</text>
TEXT = re.compile(r"<text\b[^>]*>(.*?)</text>", re.S)
NOISE = re.compile(r"<!--.*?-->|<ref\b[^>/]*/>|<ref\b[^>]*>.*?</ref\s*>", re.I | re.S)
INFOBOX = re.compile(r"\{\{\s*Infobox[ _]+([^|}\n<]*)", re.I)
BRACES = re.compile(r"\{\{|\}\}")
# | birth_date       = {{Birth date|1928|8|6}}
PARAM = re.compile(r"\n\s*\|\s*([A-Za-z_ ]+?)\s*=")
DESCRIPTION = re.compile(r"\{\{\s*Short description\s*\|([^{}]*)\}\}", re.I)
CATEGORY = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+)", re.I)
DISAMBIGUATION = re.compile(r"\{\{\s*(?:disambiguation|disambig|dab|hndis|geodis)\s*[|}]", re.I)
# {{Birth date|1928|8|6}}, {{Death date and age|1987|2|22|1928|8|6}} -> the first three numbers
DATE = re.compile(r"\{\{\s*(?:birth|death|start|end)[ _]date[^{}|]*((?:\|[^{}]*)?)\}\}", re.I)
NUMBER = re.compile(r"\|\s*(\d{1,4})\s*(?=\||$)")
# List templates keep their items: {{hlist|[[Printmaking]]|painting}} -> Printmaking, painting
LIST = re.compile(r"\{\{\s*(?:hlist|ubl|unbulleted list|plainlist|plain list|flatlist|flat list|nowrap)\s*\|",
                  re.I)
CIRCA = re.compile(r"\{\{\s*(?:circa|c\.)\s*\|", re.I)
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
# Dashes written as templates: "30 March 1853{{snd}}29 July 1890"
DASH = re.compile(r"\{\{\s*(?:snd|spnd|sndash|spndash|spaced ndash|spaced en dash|ndash|mdash|dash)\s*\}\}", re.I)
FILE = re.compile(r"^\[\[\s*(?:File|Image)\s*:.*$", re.I | re.M)
# [[Pop Art]] -> Pop Art, [[Realism (art movement)|Realism]] -> Realism
LINK = re.compile(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]")
LINE_BREAK = re.compile(r"<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")
EMPTY_BRACKETS = re.compile(r"\((?:\s*[;,])*\s*\)|(?<=\()(?:\s*[;,])+\s*")
# {{lang|fr|Arts décoratifs}} -> Arts décoratifs
LANG = re.compile(r"\{\{\s*lang\s*\|[^{}|]*\|([^{}|]*)[^{}]*\}\}", re.I)
YEAR = re.compile(r"\b(\d{3,4})\b")
HEADING = re.compile(r"\n==")
EN_WIKI_URL = re.compile(r"https?://en\.(?:m\.)?wikipedia\.org/wiki/([^?#]+)")


def en_wiki_title(url):
    """https://en.wikipedia.org/wiki/Vincent_van_Gogh -> "Vincent van Gogh"; other languages -> ""."""
    match = EN_WIKI_URL.match(url)
    return wiki_title(match[1]) if match else ""


def wiki_title(text):
    """URL path or name -> MediaWiki title: "Vincent_van_Gogh#Life" -> "Vincent van Gogh"."""
    title = " ".join(unquote(text).replace("_", " ").split("#")[0].split())
    return title[:1].upper() + title[1:]


def remove_templates(text):
    # Innermost templates first, until nested ones are gone too.
    text = DASH.sub(" – ", text)
    while True:
        text, count = TEMPLATE.subn("", text)
        if not count:
            return text


def plain(text):
    """Wikitext -> one line of plain text."""
    text = LINK.sub(r"\1", FILE.sub("", text))
    text = TAG.sub("", LINE_BREAK.sub(", ", text)).replace("'''", "").replace("''", "")
    # Entities such as &nbsp; are escaped twice in the dump: once for XML and once in the wikitext.
    text = EMPTY_BRACKETS.sub("", html.unescape(text))
    return " ".join(text.split())


def clean_value(value):
    """Infobox value -> text: dates as YYYY-MM-DD, list items separated by commas, other templates dropped."""
    value = DATE.sub(lambda match: "-".join(n.zfill(2) for n in NUMBER.findall(match[1])[:3]), value)
    value = remove_templates(CIRCA.sub("c. ", LIST.sub("", LINK.sub(r"\1", value))))
    value = plain(value.replace("{{", "").replace("}}", "").replace("|", ", ").replace("\n*", ", "))
    return ", ".join(part.strip(" *") for part in value.split(",") if part.strip(" *"))


def template_end(text, start):
    """End of the template that starts at start; nested {{...}} are counted."""
    depth = 0
    for match in BRACES.finditer(text, start):
        depth += 1 if match[0] == "{{" else -1
        if depth == 0:
            return match.end()
    return len(text)


def abstract(lead):
    """First paragraph of the article lead without templates, references and images."""
    for line in remove_templates(LANG.sub(r"\1", lead)).split("\n"):
        line = plain(line)
        if len(line) > 30 and not line.startswith(("|", "{", "}", "!", "[[")):
            return line[:1000]
    return ""


def parse_page(title, page):
    """One record from a <page> element of the dump; fields missing on the page stay empty."""
    match = TEXT.search(page)
    text = NOISE.sub("", html.unescape(match[1]) if match else "")
    record = dict.fromkeys(FIELDS, "")
    record["title"] = title
    infobox = INFOBOX.search(text)
    if infobox:
        end = template_end(text, infobox.start())
        record["infobox"] = " ".join(infobox[1].split()).lower()
        parts = PARAM.split(text[infobox.end():end - 2])
        for name, value in zip(parts[1::2], parts[2::2]):
            field = PARAMS.get(name.strip().lower().replace(" ", "_"))
            if field and not record[field]:
                record[field] = clean_value(value)
    for field in ("birth", "death"):
        year = YEAR.search(record[f"{field}_date"])
        record[f"{field}_year"] = year[1] if year else ""
    description = DESCRIPTION.search(text)
    record.update(description=plain(description[1]) if description else "",
                  categories=", ".join(" ".join(c.split()) for c in CATEGORY.findall(text)),
                  abstract=abstract(HEADING.split(text, 1)[0]),
                  disambiguation="1" if DISAMBIGUATION.search(text) else "")
    return record
