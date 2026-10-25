import math
import re
import unicodedata
from collections import Counter, defaultdict

from crawler import DATA, read_lines, write_lines
from extractor import ARTWORKS, FIELDS

INDEX = DATA.parent / "index"
# Fields with words that describe an artwork; links, the derived years and dimensions are left out.
TEXT_FIELDS = ["title", "artist", "original_title", "date", "place", "style", "genre", "media",
               "location", "period", "series", "theme", "tags", "description"]
WORD = re.compile(r"[^\W_]+")


def tokenize(text):
    """Lowercase words without diacritics: "Dürer’s Café" -> ["durer", "s", "cafe"]."""
    text = unicodedata.normalize("NFKD", text.casefold())
    return WORD.findall("".join(char for char in text if not unicodedata.combining(char)))


def artist_of(url):
    # https://www.wikiart.org/en/vincent-van-gogh/the-starry-night-1889 -> vincent-van-gogh
    return url.split("/")[4]


def read_artworks(source=ARTWORKS):
    return [dict(zip(FIELDS, line.split("\t"))) for line in read_lines(source)[1:]]


def build_index(source=ARTWORKS, target=INDEX):
    """Inverted index: term -> df, af and the (document, tf) postings; documents are artworks.tsv rows."""
    postings = defaultdict(list)
    artists = defaultdict(set)
    documents = []
    for doc, record in enumerate(read_artworks(source)):
        counts = Counter(tokenize(" ".join(record[field] for field in TEXT_FIELDS)))
        for term, tf in counts.items():
            postings[term].append(f"{doc}:{tf}")
            artists[term].add(artist_of(record["url"]))
        # Euclidean length of the log-scaled tf vector, used to normalize document weights.
        norm = math.sqrt(sum((1 + math.log10(tf)) ** 2 for tf in counts.values()))
        documents.append(f"{doc}\t{record['url']}\t{norm:.6f}")
    target.mkdir(parents=True, exist_ok=True)
    write_lines(target / "documents.tsv", ["doc\turl\tnorm"] + documents)
    write_lines(target / "postings.tsv", ["term\tdf\taf\tpostings"] + [
        f"{term}\t{len(items)}\t{len(artists[term])}\t{' '.join(items)}" for term, items in sorted(postings.items())])
    return {"documents": len(documents), "artists": len({artist_of(line.split("\t")[1]) for line in documents}),
            "terms": len(postings), "postings": sum(len(items) for items in postings.values())}


def rank(query_terms, found, weight, norms, limit):
    """Score(q, d) = sum of w(t, q) * w(t, d) with w(t, q) = tf * weight and w(t, d) = (1 + log10 tf) / |d|."""
    scores = Counter()
    for term, tf in query_terms.items():
        if term in found:
            for doc, doc_tf in found[term]["postings"]:
                scores[doc] += tf * weight[term] * (1 + math.log10(doc_tf)) / norms[doc]
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]


def search(query, index=INDEX, source=ARTWORKS, limit=10):
    """Rank artworks for a query with both idf methods and show them one after the other."""
    query_terms = Counter(tokenize(query))
    documents = [line.split("\t") for line in read_lines(index / "documents.tsv")[1:]]
    norms = [float(norm) for _, _, norm in documents]
    n = len(documents)
    a = len({artist_of(url) for _, url, _ in documents})
    found = {}
    for line in read_lines(index / "postings.tsv")[1:]:
        term, df, af, items = line.split("\t")
        if term in query_terms:
            found[term] = {"df": int(df), "af": int(af), "postings": [
                tuple(map(int, item.split(":"))) for item in items.split()]}
    # Classic idf counts documents; the inverse artist frequency counts artists who use the term.
    methods = {
        f"idf = log10(N / df), N = {n} documents": {t: math.log10(n / f["df"]) for t, f in found.items()},
        f"iaf = log10(A / af), A = {a} artists": {t: math.log10(a / f["af"]) for t, f in found.items()},
    }
    records = read_artworks(source)
    lines = [f"Query: {query}", "term\tdf\tidf\taf\tiaf"]
    for term in query_terms:
        if term in found:
            f = found[term]
            lines.append(f"{term}\t{f['df']}\t{math.log10(n / f['df']):.3f}\t{f['af']}\t{math.log10(a / f['af']):.3f}")
        else:
            lines.append(f"{term}\tnot in index")
    top = {}
    for name, weight in methods.items():
        top[name] = rank(query_terms, found, weight, norms, limit)
        lines += ["", name]
        for place, (doc, score) in enumerate(top[name], 1):
            r = records[doc]
            lines.append(f"{place:2}. {score:.4f}  {r['title']} - {r['artist']}, {r['date'] or '?'} "
                         f"({r['style'] or '?'})  {r['url']}")
    first, second = (set(doc for doc, _ in docs) for docs in top.values())
    lines += ["", f"Common results in both top {limit}: {len(first & second)}"]
    return "\n".join(lines)
