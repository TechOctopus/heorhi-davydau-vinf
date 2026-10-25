import os

import tiktoken

from crawler import DATA, read_lines, read_records, summarize
from extractor import ARTWORKS, FIELDS
from indexer import INDEX, TEXT_FIELDS, read_artworks

NO_MUSEUM = {"", "Private Collection", "unknown", "Whereabouts Unknown"}


def corpus_stats():
    """Crawl counts from the logs plus how many records can answer the project questions."""
    records = read_artworks()
    years = [(int(r["year_from"]), int(r["year_to"])) for r in records if r["year_from"]]
    return {
        "crawl": summarize(DATA),
        "artworks": len(records),
        "artworks_tsv_bytes": ARTWORKS.stat().st_size,
        "index_terms": len(read_lines(INDEX / "postings.tsv")) - 1,
        "index_bytes": sum(path.stat().st_size for path in INDEX.iterdir()),
        # Same metadata is only a candidate duplicate: series such as Monet's Water Lilies share it.
        "same_metadata_except_url": len(records) - len({tuple(r[f] for f in FIELDS[1:]) for r in records}),
        "relevant": {
            "artist": sum(bool(r["artist"]) for r in records),
            "style_impressionism": sum("Impressionism" in r["style"].split(", ") for r in records),
            "year": len(years),
            "year_1850_1900": sum(start <= 1900 and end >= 1850 for start, end in years),
            "museum": sum(r["location"] not in NO_MUSEUM for r in records),
            "artist_wikipedia": sum(bool(r["artist_wikipedia"]) for r in records),
        },
    }


def count_tokens(encoding="o200k_base", batch=500):
    """tiktoken tokens of all saved HTML and of the indexed record text (takes about 15 minutes)."""
    tokenizer = tiktoken.get_encoding(encoding)
    pages = [row for row in read_records(DATA) if row["file"]]
    html_tokens = 0
    for start in range(0, len(pages), batch):
        documents = [(DATA / row["file"]).read_bytes().decode(row["encoding"], errors="replace")
                     for row in pages[start:start + batch]]
        html_tokens += sum(map(len, tokenizer.encode_ordinary_batch(documents, num_threads=os.cpu_count())))
    texts = [" ".join(r[field] for field in TEXT_FIELDS) for r in read_artworks()]
    return {"encoding": encoding, "html_pages": len(pages), "html_tokens": html_tokens,
            "records": len(texts), "record_tokens": sum(map(len, tokenizer.encode_ordinary_batch(texts)))}
