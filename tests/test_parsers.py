"""Tests for Context Forge parsers."""

import json
import os
import tempfile
import unittest

from context_forge.parsers.youtube import extract_video_id, parse_watch_history_json
from context_forge.parsers.chatgpt import parse_conversations_json, _extract_messages_from_mapping
from context_forge.parsers.chrome import parse_bookmarks_html


class TestYouTubeParser(unittest.TestCase):
    def test_extract_video_id_standard(self):
        self.assertEqual(
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extract_video_id_short(self):
        self.assertEqual(
            extract_video_id("https://youtu.be/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extract_video_id_embed(self):
        self.assertEqual(
            extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extract_video_id_invalid(self):
        self.assertIsNone(extract_video_id("https://example.com"))

    def test_parse_watch_history_json(self):
        data = [
            {
                "title": "Watched Test Video",
                "titleUrl": "https://www.youtube.com/watch?v=abc12345678",
                "time": "2025-01-15T10:30:00Z",
                "subtitles": [{"name": "Test Channel"}],
            },
            {
                "title": "Visited some page",
                "titleUrl": "https://www.youtube.com/feed",
            },
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            entries = parse_watch_history_json(f.name)

        os.unlink(f.name)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Test Video")
        self.assertEqual(entries[0]["video_id"], "abc12345678")
        self.assertEqual(entries[0]["channel"], "Test Channel")


class TestChatGPTParser(unittest.TestCase):
    def test_extract_messages_from_mapping(self):
        mapping = {
            "root": {
                "parent": None,
                "message": None,
            },
            "msg1": {
                "parent": "root",
                "message": {
                    "author": {"role": "user"},
                    "content": {"parts": ["Hello, how are you?"]},
                    "create_time": 1700000000,
                },
            },
            "msg2": {
                "parent": "msg1",
                "message": {
                    "author": {"role": "assistant"},
                    "content": {"parts": ["I'm doing well!"]},
                    "create_time": 1700000001,
                },
            },
        }

        messages = _extract_messages_from_mapping(mapping)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "Hello, how are you?")
        self.assertEqual(messages[1]["role"], "assistant")

    def test_parse_conversations_json(self):
        data = [
            {
                "id": "conv1",
                "title": "Test Conversation",
                "create_time": 1700000000,
                "update_time": 1700000100,
                "mapping": {
                    "root": {"parent": None, "message": None},
                    "m1": {
                        "parent": "root",
                        "message": {
                            "author": {"role": "user"},
                            "content": {"parts": ["test"]},
                        },
                    },
                },
            }
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            convs = parse_conversations_json(f.name)

        os.unlink(f.name)

        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["source"], "chatgpt")
        self.assertEqual(convs[0]["title"], "Test Conversation")


class TestChromeParser(unittest.TestCase):
    def test_parse_bookmarks_html(self):
        html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3>Dev</H3>
    <DL><p>
        <DT><A HREF="https://github.com">GitHub</A>
        <DT><A HREF="https://stackoverflow.com">Stack Overflow</A>
    </DL><p>
</DL><p>"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(html)
            f.flush()
            bookmarks = parse_bookmarks_html(f.name)

        os.unlink(f.name)

        self.assertEqual(len(bookmarks), 2)
        self.assertEqual(bookmarks[0]["title"], "GitHub")
        self.assertEqual(bookmarks[0]["url"], "https://github.com")
        self.assertEqual(bookmarks[0]["folder"], "Dev")


class TestQueueDB(unittest.TestCase):
    def test_queue_operations(self):
        from context_forge.queue_db import ImportQueueDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test-queue.db")
            db = ImportQueueDB(db_path)
            db.init_db()

            # Add item
            self.assertTrue(db.add_item("gemini", "conv1", metadata='{"title": "test"}'))

            # Duplicate
            self.assertFalse(db.add_item("gemini", "conv1"))

            # Check exists
            self.assertTrue(db.exists("gemini", "conv1"))
            self.assertFalse(db.exists("gemini", "conv2"))

            # Get pending
            pending = db.get_pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["source"], "gemini")

            # Mark complete
            db.mark_complete(pending[0]["id"])
            self.assertEqual(len(db.get_pending()), 0)

            counts = db.get_status_counts()
            self.assertEqual(counts.get("complete"), 1)

            db.close()


if __name__ == "__main__":
    unittest.main()
