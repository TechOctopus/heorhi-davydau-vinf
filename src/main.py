import argparse
import json
import logging
from pathlib import Path

from crawler import DEFAULT_ARTISTS, SLUG, CrawlStopped, crawl, summarize

def main():
    parser = argparse.ArgumentParser(description="Download and resume a focused WikiArt HTML sample.")
    parser.add_argument("command", choices=["crawl", "stats"])
    parser.add_argument("--output", type=Path, default=Path("data/wikiart"))
    parser.add_argument("--artist", action="append", help="Artist slug; repeat for multiple artists.")
    parser.add_argument("--max-pages", type=int, default=12, help="Target total saved pages, including previous runs (default: 12).")
    parser.add_argument("--delay", type=float, default=2.0, help="Minimum seconds between request starts (at least 1; default: 2).")
    args = parser.parse_args()
    if args.max_pages < 1 or not 1 <= args.delay <= 60:
        parser.error("--max-pages must be positive; --delay must be between 1 and 60 seconds")
    artists = list(dict.fromkeys(args.artist or DEFAULT_ARTISTS))
    if any(not SLUG.fullmatch(artist) for artist in artists):
        parser.error("Artist slugs must use lowercase letters, digits, and hyphens")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "stats":
            if not (args.output / "state.json").exists():
                parser.error(f"No crawl found in {args.output}; run crawl first")
            summary = summarize(args.output)
        else:
            summary = crawl(args.output, artists, args.max_pages, args.delay)
    except KeyboardInterrupt:
        print("\nStopped. Progress saved; run the same command to resume.")
        return 0
    except (CrawlStopped, ValueError, OSError) as error:
        logging.error("%s", error)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
