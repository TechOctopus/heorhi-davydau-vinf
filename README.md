# heorhi davydau vinf project

Paintings search engine (FIIT STU, VINF)

## Run

```bash
uv sync --locked                                 # install dependencies
uv run src/main.py crawl --max-pages 12          # small sample (Van Gogh, Monet, Klimt)
uv run src/main.py crawl                         # full crawl
uv run src/main.py stats                         # counts from the checkpoint (works during a crawl)
tail -f data/crawl.log                           # log
```

## Crawl output (`data/wikiart/`)

| File | Content |
|---|---|
| `frontier.txt` | Every discovered URL in discovery order (append-only) |
| `pages.tsv` | One metadata row per processed URL (append-only) |
| `raw/*.html` | Unchanged HTML, named by SHA-256 of the URL |
| `state.json` | Selected artists and request settings |
| `summary.json` | Statistics regenerated from the logs |

The queue is `frontier.txt` minus URLs already in `pages.tsv`, so an interrupted
crawl resumes where it stopped.