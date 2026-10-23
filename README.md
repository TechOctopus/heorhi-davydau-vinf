# heorhi davydau vinf project

Paintings search engine (FIIT STU, VINF)

## Run

```bash
uv sync --locked                                       # install dependencies
nohup uv run src/main.py crawl >> data/crawl.log 2>&1 &  # crawl in the background; rerun to resume
tail -f data/crawl.log                                 # follow the log
uv run src/main.py stats                               # counts from the logs (works during a crawl)
uv run src/main.py extract                             # artwork records -> data/artworks.tsv
uv run python -m unittest discover -s tests -v         # extractor tests on 22 saved pages
```

The crawl starts from the WikiArt artist lists in `SEEDS` (`src/crawler.py`):
popular artists and the Impressionism, Post-Impressionism and Realism movements.
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
