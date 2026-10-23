import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from crawler import read_lines
from extractor import FIELDS, extract_artwork

PAGES = Path(__file__).parent / "pages"


class ExtractorTest(unittest.TestCase):
    def test_saved_pages(self):
        # One record per saved page, checked against the page; same columns as data/artworks.tsv.
        for line in read_lines(PAGES / "expected.tsv")[1:]:
            expected = dict(zip(FIELDS, line.split("\t")))
            # https://www.wikiart.org/en/vincent-van-gogh/dog -> vincent-van-gogh_dog.html
            page = PAGES / (expected["url"].split("/en/")[1].replace("/", "_") + ".html")
            with self.subTest(expected["url"]):
                self.assertEqual(extract_artwork(page.read_text(encoding="utf-8"), expected["url"]), expected)


if __name__ == "__main__":
    unittest.main()
