# heorhi davydau vinf project

Paintings search engine (FIIT STU, VINF)

## Run

```bash
uv sync --locked                                 # install dependencies
uv run src/main.py crawl --max-pages 12          # small sample (Van Gogh, Monet, Klimt)
uv run src/main.py crawl                         # full crawl
uv run src/main.py stats                         # counts from the checkpoint (works during a crawl)
uv run python -m unittest discover -s tests -v   # offline tests
tail -f data/crawl.log                           # log
```