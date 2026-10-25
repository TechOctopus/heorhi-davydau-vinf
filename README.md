# heorhi davydau vinf project

Paintings search engine (FIIT STU, VINF)

## Run

```bash
uv sync --locked                                       # install dependencies
nohup uv run src/main.py crawl >> data/crawl.log 2>&1 &  # crawl in the background; rerun to resume
tail -f data/crawl.log                                 # follow the log
uv run src/main.py extract                             # artwork records -> data/artworks.tsv
uv run src/main.py index                               # inverted index -> data/index/
uv run src/main.py search van gogh sunflowers          # top 10 with both idf methods
uv run src/main.py stats                               # crawl, record and index statistics
uv run src/main.py tokens                              # tiktoken token counts (about 15 min)
uv run python -m unittest discover -s tests -v         # extractor tests on 25 saved pages
```

The crawl starts from the WikiArt artist lists in `SEEDS` (`src/crawler.py`):
popular artists and the Impressionism, Post-Impressionism, Realism and
Romanticism movements.
Stop it with `kill <PID>` or Ctrl+C; the same command continues where it stopped.

## Crawl output (`data/wikiart/`)

| File | Content |
|---|---|
| `frontier.txt` | Every discovered URL in discovery order (append-only) |
| `pages.tsv` | One metadata row per processed URL (append-only) |
| `artists.txt` | Artists found on the seed lists (append-only) |
| `raw/*.html` | Unchanged HTML, named by SHA-256 of the URL |
| `summary.json` | Statistics regenerated from the logs |

The queue is `frontier.txt` minus URLs already in `pages.tsv`.

## Extracted records (`data/artworks.tsv`)

`extract` reads every saved artwork page and writes one TSV row per page with
regular expressions (`src/extractor.py`): title, artist and their Wikipedia
link, original title, date with years and place, style, genre, media, location,
dimensions, period, series, theme, tags, the artwork's Wikipedia link and
description. Fields missing on a page stay empty. The tests compare the output
for the pages in `tests/pages/` with `tests/pages/expected.tsv`.

## Index and search (`data/index/`)

`index` turns every `artworks.tsv` row into a document of words from its text
fields (lowercase, without diacritics) and writes our own inverted index:

| File | Content |
|---|---|
| `postings.tsv` | `term`, `df` (documents), `af` (artists), postings `doc:tf ...` |
| `documents.tsv` | `doc` (row in `artworks.tsv`), `url`, Euclidean length of the `1 + log10 tf` vector |

`search` scores documents as in lecture 06: query weight `tf × idf`, document
weight `(1 + log10 tf) / length`, score = sum over query terms. It prints the top 10
for two term weights:

- `idf = log10(N / df)`: the classic inverse document frequency, N = documents;
- `iaf = log10(A / af)`: inverse artist frequency, A = artists. A word is
  specific when few artists use it, however many works a prolific artist has.

Rebuild the index after every `extract`; document ids are `artworks.tsv` rows.
