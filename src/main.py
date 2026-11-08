import argparse
import json
import logging

from crawler import CrawlStopped, crawl
from extractor import extract
from indexer import build_index, search
from spark_jobs import spark_extract, spark_join, spark_wiki
from stats import corpus_stats, count_tokens

COMMANDS = {"crawl": crawl, "stats": corpus_stats, "extract": extract, "index": build_index,
            "tokens": count_tokens, "spark-extract": spark_extract,
            "wiki": spark_wiki, "join": spark_join}


def main():
    parser = argparse.ArgumentParser(description="Paintings search engine over WikiArt data.")
    parser.add_argument("command", choices=[*COMMANDS, "search"])
    parser.add_argument("query", nargs="*", help="words to search for (search command only)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "search":
            print(search(" ".join(args.query)))
            return 0
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
