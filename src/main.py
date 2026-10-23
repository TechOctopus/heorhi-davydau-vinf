import argparse
import json
import logging

from crawler import DATA, CrawlStopped, crawl, summarize
from extractor import extract

COMMANDS = {"crawl": crawl, "stats": lambda: summarize(DATA), "extract": extract}


def main():
    parser = argparse.ArgumentParser(description="Paintings search engine over WikiArt data.")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        summary = COMMANDS[args.command]()
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
