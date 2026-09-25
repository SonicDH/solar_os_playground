import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FakeStorage:
    @staticmethod
    def mkdir(path):
        os.mkdir(path)

    @staticmethod
    def remove(path):
        os.remove(path)

    @staticmethod
    def rename(source, destination):
        os.replace(source, destination)

    @staticmethod
    def rmdir(path):
        os.rmdir(path)


def load_app(app_id):
    tui = types.SimpleNamespace()
    solaros = types.ModuleType("solaros")
    solaros.tui = tui
    solaros.storage = FakeStorage()
    solaros.should_exit = lambda: False
    previous = sys.modules.get("solaros")
    sys.modules["solaros"] = solaros
    try:
        path = ROOT / "apps" / app_id / (app_id + ".py")
        spec = importlib.util.spec_from_file_location("test_" + app_id, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            del sys.modules["solaros"]
        else:
            sys.modules["solaros"] = previous


class RssMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rss = load_app("rss")

    def test_entity_decoder_preserves_text_and_decodes_entities(self):
        self.assertEqual(
            "plain & punctuation ' --",
            self.rss.decode_entities("plain &amp; punctuation &#8217; &mdash;"),
        )

    def test_large_html_render_is_bounded(self):
        rendered = self.rss.rendered_text(
            "<p>" + ("word " * 10000) + "</p>",
            self.rss.ARTICLE_LIMIT,
        )
        self.assertLessEqual(len(rendered), self.rss.ARTICLE_LIMIT)
        self.assertTrue(rendered.startswith("word word"))

    def test_large_feed_entry_parses_without_full_feed_copy(self):
        description = "<p>" + ("word " * 8000) + "</p>"
        feed = (
            "<?xml version='1.0'?><rss><channel><title>Test</title>"
            "<item><title>Large</title><guid>1</guid><description><![CDATA["
            + description
            + "]]></description></item></channel></rss>"
        )
        self.rss.save_article = lambda post, body: None
        with tempfile.NamedTemporaryFile("wb") as source:
            source.write(feed.encode("utf-8"))
            source.flush()
            title, posts = self.rss.parse_feed_file(
                source.name, {"url": "https://example.test/feed", "title": ""}, 1
            )
        self.assertEqual("Test", title)
        self.assertEqual(1, len(posts))
        self.assertLessEqual(len(posts[0]["summary"]), 512)

    def test_help_bar_spans_width_and_bolds_mnemonics(self):
        calls = []
        self.rss.tui.INVERSE = 1
        self.rss.tui.BOLD = 2
        self.rss.tui.addstr = lambda *args: calls.append(args)

        self.rss.draw_help(7, 24, "Open link  Read aloud",
                           (("Open link", 0), ("Read aloud", 0)))

        self.assertEqual((7, 0, " " * 24, self.rss.tui.INVERSE), calls[0])
        self.assertEqual("O", calls[2][2])
        self.assertEqual(self.rss.tui.INVERSE | self.rss.tui.BOLD, calls[2][3])
        self.assertEqual("R", calls[3][2])
        self.assertEqual(self.rss.tui.INVERSE | self.rss.tui.BOLD, calls[3][3])

    def test_read_aloud_is_silent_when_speechd_is_not_running(self):
        class StoppedSpeech:
            def __init__(self):
                self.spoken = []

            @staticmethod
            def queue_status():
                return {"running": False}

            def say(self, text):
                self.spoken.append(text)

        speech = StoppedSpeech()
        self.rss.solaros.speech = speech
        self.rss.read_aloud({"title": "News"}, "Article body")
        self.assertEqual([], speech.spoken)

    def test_read_aloud_enqueues_bounded_chunks(self):
        class RunningSpeech:
            def __init__(self):
                self.spoken = []
                self.cancelled = []
                self.queued = 0
                self.capacity = 2

            def queue_status(self):
                return {"running": True, "queued": self.queued,
                        "capacity": self.capacity, "current_id": 0}

            def say(self, text):
                self.assert_chunk(text)
                self.spoken.append(text)
                self.queued += 1
                return len(self.spoken)

            def cancel(self, request_id):
                self.cancelled.append(request_id)

            @staticmethod
            def assert_chunk(text):
                if len(text.encode("utf-8")) > 512:
                    raise AssertionError("speech chunk exceeds API limit")

        speech = RunningSpeech()
        self.rss.solaros.speech = speech
        state = self.rss.read_aloud(
            {"title": "News"}, ("word " * 1600) + (" caf\u00e9" * 200))
        active_state = state
        submitted = len(speech.spoken)
        self.rss.cancel_read_aloud(active_state)
        self.assertEqual(list(range(1, submitted + 1)), speech.cancelled)

        speech.cancelled = []
        speech.queued = 0
        state = self.rss.read_aloud(
            {"title": "News"}, ("word " * 1600) + (" caf\u00e9" * 200))
        while state is not None:
            speech.queued = 0
            state = self.rss.pump_read_aloud(state)
        self.assertGreater(len(speech.spoken), 1)
        self.assertTrue(speech.spoken[0].startswith("News."))
        self.assertTrue(all(len(chunk.encode("utf-8")) <=
                            self.rss.SPEECH_CHUNK_LIMIT
                            for chunk in speech.spoken))

    def test_speech_omits_image_placeholders(self):
        chunks = self.rss.speech_chunks(
            "News", "Before [Image: photo.jpg] after.\n[Image: ]\nEnding.")
        spoken = " ".join(chunks)
        self.assertNotIn("[Image:", spoken)
        self.assertNotIn("photo.jpg", spoken)
        self.assertIn("Before  after.", spoken)
        self.assertIn("Ending.", spoken)


class WikipediaMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wikipedia = load_app("wikipedia")

    def test_long_extract_without_newline_is_processed_in_bounded_segments(self):
        source_text = (
            "<?xml version='1.0'?><api><extract>"
            + ("word " * 24000)
            + "&#65;</extract></api>"
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xml"
            body = Path(directory) / "body.txt"
            source.write_text(source_text)
            self.wikipedia.parse_extract_xml(str(source), str(body), 40)
            rendered = body.read_text()
        self.assertIn("word word", rendered)
        self.assertIn("A", rendered)
        self.assertNotIn("&#65;", rendered)

    def test_article_source_is_removed_when_streaming_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            self.wikipedia.CACHE_DIR = directory
            self.wikipedia.tui.size = lambda: (24, 80)

            def fail_stream(unused_url, path):
                Path(path).write_text("partial")
                raise MemoryError()

            self.wikipedia.stream_article = fail_stream
            with self.assertRaises(MemoryError):
                self.wikipedia.prepare_article(
                    {"language": "en"}, "Test", "Test", "en"
                )
            article_dir, unused_body, unused_links = self.wikipedia.article_paths(
                "Test", "en"
            )
            self.assertFalse((Path(article_dir) / "source.xml").exists())


if __name__ == "__main__":
    unittest.main()
