import argparse
import json
import logging

from crawler import DATA, CrawlStopped, crawl, summarize


def main():
    parser = argparse.ArgumentParser(description="Paintings search engine over WikiArt data.")
    parser.add_argument("command", choices=["crawl", "stats"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        summary = crawl() if args.command == "crawl" else summarize(DATA)
    except KeyboardInterrupt:
        print("\nStopped. Progress saved; run the same command to resume.")
        return 0
    except (CrawlStopped, OSError) as error:
        logging.error("%s", error)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
