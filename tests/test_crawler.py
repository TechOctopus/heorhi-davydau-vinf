import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from crawler import (BASE_URL, CrawlStopped, PoliteClient, crawl, extract_links,
                     normalize_url, retry_after)

ARTIST = "vincent-van-gogh"
LIST = f"{BASE_URL}/en/{ARTIST}/all-works/text-list"
ART = f"{BASE_URL}/en/{ARTIST}/the-starry-night-1889"
ROBOTS = BASE_URL + "/robots.txt"


def page(title, links=""):
    return 200, {"Content-Type": "text/html; charset=utf-8"}, f"<title>{title}</title>{links}".encode()


def fake_client(responses):
    client = Mock()
    client.delay = 2
    client.get.side_effect = lambda url: responses[url]
    return client


class LinkTests(unittest.TestCase):
    def test_normalization_and_crawl_boundary(self):
        self.assertEqual(normalize_url(f"http://wikiart.org/en/{ARTIST}/the-starry-night-1889/#top", LIST, [ARTIST]), ART)
        for link in ["https://example.com/en/vincent-van-gogh/work", "/en/claude-monet/work",
                     "/en/vincent-van-gogh", "/de/vincent-van-gogh/work", "/en/vincent-van-gogh/work?json=1",
                     "javascript:alert(1)", "/en/vincent-van-gogh/work.jpg", "https://www.wikiart.org:443/en/vincent-van-gogh/work"]:
            with self.subTest(link=link):
                self.assertIsNone(normalize_url(link, LIST, [ARTIST]))

    def test_percent_encoded_and_underscore_slugs_are_artworks(self):
        for slug in ["portrait-of-p%C3%A8re-tanguy-1887", "not_detected_212152"]:
            with self.subTest(slug=slug):
                self.assertEqual(normalize_url(f"/en/{ARTIST}/{slug}", LIST, [ARTIST]), f"{BASE_URL}/en/{ARTIST}/{slug}")
        for slug in ["bad%zz", "bad%2", "a.jpg", "a b"]:
            with self.subTest(slug=slug):
                self.assertIsNone(normalize_url(f"/en/{ARTIST}/{slug}", LIST, [ARTIST]))

    def test_regex_links_handle_quotes_and_ignore_scripts(self):
        document = f'''<a href="{ART}#top">one</a><a href='{ART}'>duplicate</a>
        <A class="x" HREF=/en/{ARTIST}/irises-1889>two</A>
        <script>const x = '<a href="/en/{ARTIST}/fake">';</script>
        <!-- <a href="/en/{ARTIST}/comment"> -->'''
        self.assertEqual(extract_links(document, LIST, [ARTIST]), [ART, f"{BASE_URL}/en/{ARTIST}/irises-1889"])


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.responses = {
            ROBOTS: (200, {}, b"User-agent: *\nAllow: /\n"),
            LIST: page("Artist works", f'<a href="{ART}">painting</a>'),
            ART: page("The Starry Night"),
        }

    def test_resume_skips_saved_pages_and_limit_means_total(self):
        first = fake_client(self.responses)
        self.assertEqual(crawl(self.output, [ARTIST], 1, client=first)["saved_pages"], 1)
        second = fake_client(self.responses)
        summary = crawl(self.output, [ARTIST], 2, client=second)
        self.assertEqual([call.args[0] for call in second.get.call_args_list], [ROBOTS, ART])
        self.assertEqual(summary["saved_pages"], 2)
        self.assertEqual(summary["artwork_pages"], 1)
        third = fake_client({})
        crawl(self.output, [ARTIST], 2, client=third)
        third.get.assert_not_called()
        self.assertEqual(len(list((self.output / "raw").glob("*.html"))), 2)

    def test_interrupt_keeps_current_url_in_queue(self):
        client = fake_client(self.responses)
        def fetch(url):
            if url == ART:
                raise KeyboardInterrupt
            return self.responses[url]
        client.get.side_effect = fetch
        with self.assertRaises(KeyboardInterrupt):
            crawl(self.output, [ARTIST], 2, client=client)
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["pending"], [ART])
        self.assertEqual(len(state["records"]), 1)
        summary = crawl(self.output, [ARTIST], 2, client=fake_client(self.responses))
        self.assertEqual(summary["saved_pages"], 2)

    def test_robots_denial_and_delay(self):
        self.responses[ROBOTS] = (200, {}, f"User-agent: *\nDisallow: /en/{ARTIST}/the-starry-night-1889\nCrawl-delay: 5".encode())
        client = fake_client(self.responses)
        summary = crawl(self.output, [ARTIST], 2, client=client)
        self.assertEqual(client.delay, 5)
        self.assertEqual([call.args[0] for call in client.get.call_args_list], [ROBOTS, LIST])
        self.assertEqual(summary["skipped_or_failed"], 1)

    def test_redirects_cannot_escape_scope(self):
        self.responses[ART] = (302, {"Location": "https://example.com/"}, b"")
        client = fake_client(self.responses)
        summary = crawl(self.output, [ARTIST], 2, client=client)
        self.assertEqual(summary["saved_pages"], 1)
        self.assertEqual(summary["skipped_or_failed"], 1)
        self.assertEqual(client.get.call_count, 3)

    def test_blocked_response_preserves_queue(self):
        self.responses[ART] = (403, {}, b"blocked")
        with self.assertRaises(CrawlStopped):
            crawl(self.output, [ARTIST], 2, client=fake_client(self.responses))
        state = json.loads((self.output / "state.json").read_text())
        self.assertEqual(state["pending"], [ART])

    def test_missing_page_recorded_without_saving_html(self):
        self.responses[ART] = (404, {"Content-Type": "text/html"}, b"missing")
        summary = crawl(self.output, [ARTIST], 2, client=fake_client(self.responses))
        self.assertEqual(summary["saved_pages"], 1)
        self.assertEqual(summary["http_statuses"], {"200": 1, "404": 1})

    def test_unavailable_robots_stops_before_page_requests(self):
        self.responses[ROBOTS] = (503, {}, b"unavailable")
        client = fake_client(self.responses)
        with self.assertRaises(CrawlStopped):
            crawl(self.output, [ARTIST], 2, client=client)
        self.assertEqual(client.get.call_count, 1)


class HttpTests(unittest.TestCase):
    def response(self, status, headers=None, body=b"ok"):
        response = Mock(status_code=status, headers=headers or {})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [body]
        return response

    @patch("crawler.time.sleep")
    def test_retry_after_and_explicit_request_settings(self, sleep):
        client = PoliteClient()
        self.addCleanup(client.session.close)
        with patch.object(client.session, "get", side_effect=[self.response(429, {"Retry-After": "5"}), self.response(200)]) as get:
            self.assertEqual(client.get(ART)[0], 200)
            self.assertTrue(any(call.args[0] >= 5 for call in sleep.call_args_list))
            self.assertEqual(get.call_args.kwargs["timeout"], (10, 30))
            self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("crawler.time.sleep")
    def test_network_retries_are_bounded(self, sleep):
        client = PoliteClient()
        self.addCleanup(client.session.close)
        with patch.object(client.session, "get", side_effect=requests.Timeout("timeout")) as get:
            with self.assertRaises(CrawlStopped):
                client.get(ART)
            self.assertEqual(get.call_count, 3)

    @patch("crawler.time.sleep")
    def test_long_retry_after_stops_instead_of_retrying_early(self, sleep):
        client = PoliteClient()
        self.addCleanup(client.session.close)
        with patch.object(client.session, "get", return_value=self.response(429, {"Retry-After": "3600"})) as get:
            with self.assertRaises(CrawlStopped):
                client.get(ART)
            self.assertEqual(get.call_count, 1)

    def test_retry_after_accepts_http_dates_and_invalid_values(self):
        self.assertGreater(retry_after("Wed, 01 Jan 2098 00:00:00 GMT"), 0)
        self.assertEqual(retry_after("invalid"), 0)


if __name__ == "__main__":
    unittest.main()
