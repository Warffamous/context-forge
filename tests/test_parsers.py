"""Tests for Context Forge parsers."""

import json
import os
import tempfile
import unittest

from context_forge.parsers.youtube import extract_video_id, parse_watch_history_json
from context_forge.parsers.chatgpt import (
    parse_conversations_json,
    _extract_messages_from_mapping,
    _load_chatgpt_json,
    _is_split_filename,
    find_chatgpt_data,
)
from context_forge.parsers.youtube import find_youtube_data
from context_forge.parsers.grok import parse_grok_json, find_grok_data, parse_all_grok
from context_forge.parsers.gemini_text import (
    parse_gemini_text_file,
    find_gemini_text_files,
    parse_all_gemini_text,
    _detect_turn_markers,
    _split_into_conversations,
)
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


    def test_split_file_detection(self):
        self.assertTrue(_is_split_filename("conversations-000.json"))
        self.assertTrue(_is_split_filename("conversations-013.json"))
        self.assertFalse(_is_split_filename("conversations.json"))
        self.assertFalse(_is_split_filename("other-file.json"))

    def test_parse_split_files(self):
        """Test loading ChatGPT conversations from multiple split files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create split files
            for i in range(3):
                data = [
                    {
                        "id": f"conv_{i}_{j}",
                        "title": f"Conversation {i}-{j}",
                        "mapping": {
                            "root": {"parent": None, "message": None},
                            "m1": {
                                "parent": "root",
                                "message": {
                                    "author": {"role": "user"},
                                    "content": {"parts": [f"msg {i}-{j}"]},
                                },
                            },
                        },
                    }
                    for j in range(2)
                ]
                path = os.path.join(tmpdir, f"conversations-{i:03d}.json")
                with open(path, "w") as f:
                    json.dump(data, f)

            # Test loading from directory
            result = _load_chatgpt_json(tmpdir)
            self.assertEqual(len(result), 6)  # 3 files × 2 conversations

            # Test find_chatgpt_data with directory
            found = find_chatgpt_data(tmpdir)
            self.assertIn("conversations", found)
            self.assertEqual(found["file_count"], 3)

            # Test parse_conversations_json with directory
            convs = parse_conversations_json(tmpdir)
            self.assertEqual(len(convs), 6)
            self.assertEqual(convs[0]["source"], "chatgpt")

    def test_parse_split_file_by_single_path(self):
        """Test that pointing to one split file loads all siblings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(2):
                data = [{"id": f"conv_{i}", "title": f"Conv {i}", "mapping": {
                    "root": {"parent": None, "message": None},
                }}]
                path = os.path.join(tmpdir, f"conversations-{i:03d}.json")
                with open(path, "w") as f:
                    json.dump(data, f)

            # Point to just the first file — should find all siblings
            single_path = os.path.join(tmpdir, "conversations-000.json")
            result = _load_chatgpt_json(single_path)
            self.assertEqual(len(result), 2)

            found = find_chatgpt_data(single_path)
            self.assertEqual(found["file_count"], 2)


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


class TestYouTubeFindData(unittest.TestCase):
    def test_standard_structure(self):
        """Test finding YouTube data in standard Takeout structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create standard structure
            yt_dir = os.path.join(tmpdir, "YouTube and YouTube Music", "history")
            os.makedirs(yt_dir)
            with open(os.path.join(yt_dir, "watch-history.json"), "w") as f:
                json.dump([], f)

            found = find_youtube_data(tmpdir)
            self.assertIn("watch_history", found)

    def test_empty_youtube_folder_diagnostics(self):
        """Test that an empty YouTube folder reports diagnostics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create YouTube folder with no data files (multi-part export scenario)
            yt_dir = os.path.join(tmpdir, "YouTube and YouTube Music")
            os.makedirs(yt_dir)

            found = find_youtube_data(tmpdir)
            self.assertNotIn("watch_history", found)
            self.assertIn("_yt_dir", found)
            self.assertIn("_available_files", found)

    def test_youtube_folder_with_some_files(self):
        """Test that YouTube folder with non-history files lists them in diagnostics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yt_dir = os.path.join(tmpdir, "YouTube and YouTube Music")
            os.makedirs(os.path.join(yt_dir, "playlists"))
            # Write some non-history file
            with open(os.path.join(yt_dir, "playlists", "some-playlist.json"), "w") as f:
                json.dump([], f)

            found = find_youtube_data(tmpdir)
            self.assertNotIn("watch_history", found)
            self.assertIn("_available_files", found)
            self.assertIn("playlists/some-playlist.json", found["_available_files"])

    def test_alternative_watch_history_location(self):
        """Test finding watch history at root of YouTube folder (not in history/ subfolder)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yt_dir = os.path.join(tmpdir, "YouTube and YouTube Music")
            os.makedirs(yt_dir)
            with open(os.path.join(yt_dir, "watch-history.json"), "w") as f:
                json.dump([], f)

            found = find_youtube_data(tmpdir)
            self.assertIn("watch_history", found)

    def test_my_activity_youtube_fallback(self):
        """Test finding watch history via My Activity/YouTube/MyActivity.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # No YouTube folder at all — only My Activity
            activity_dir = os.path.join(tmpdir, "My Activity", "YouTube")
            os.makedirs(activity_dir)
            with open(os.path.join(activity_dir, "MyActivity.json"), "w") as f:
                json.dump([], f)

            found = find_youtube_data(tmpdir)
            self.assertIn("watch_history", found)
            self.assertIn("MyActivity.json", found["watch_history"])

    def test_my_activity_with_empty_youtube_folder(self):
        """Test My Activity path is found when YouTube folder exists but is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty YouTube folder (multi-part export — history is elsewhere)
            yt_dir = os.path.join(tmpdir, "YouTube and YouTube Music")
            os.makedirs(yt_dir)

            # But My Activity has the data
            activity_dir = os.path.join(tmpdir, "My Activity", "YouTube")
            os.makedirs(activity_dir)
            with open(os.path.join(activity_dir, "MyActivity.json"), "w") as f:
                json.dump([], f)

            found = find_youtube_data(tmpdir)
            self.assertIn("watch_history", found)
            self.assertIn("MyActivity.json", found["watch_history"])


class TestChatGPTDeduplication(unittest.TestCase):
    def test_split_files_deduplication(self):
        """Test that duplicate conversations across split files are deduplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two split files with an overlapping conversation
            data_0 = [
                {"id": "conv_a", "title": "Conv A", "mapping": {
                    "root": {"parent": None, "message": None},
                    "m1": {"parent": "root", "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["hello"]},
                    }},
                }},
                {"id": "conv_b", "title": "Conv B", "mapping": {
                    "root": {"parent": None, "message": None},
                }},
            ]
            data_1 = [
                {"id": "conv_b", "title": "Conv B Updated", "mapping": {
                    "root": {"parent": None, "message": None},
                    "m1": {"parent": "root", "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["world"]},
                    }},
                }},
                {"id": "conv_c", "title": "Conv C", "mapping": {
                    "root": {"parent": None, "message": None},
                }},
            ]
            with open(os.path.join(tmpdir, "conversations-000.json"), "w") as f:
                json.dump(data_0, f)
            with open(os.path.join(tmpdir, "conversations-001.json"), "w") as f:
                json.dump(data_1, f)

            convs = parse_conversations_json(tmpdir)
            ids = [c["id"] for c in convs]
            # conv_b should appear only once (deduplicated)
            self.assertEqual(ids.count("conv_b"), 1)
            # Should have 3 unique conversations
            self.assertEqual(len(convs), 3)
            # The later occurrence of conv_b should win (has "world" message)
            conv_b = [c for c in convs if c["id"] == "conv_b"][0]
            self.assertEqual(conv_b["title"], "Conv B Updated")


class TestGrokParser(unittest.TestCase):
    def test_parse_conversation_objects(self):
        """Test parsing Grok JSON with conversation objects."""
        data = [
            {
                "id": "grok_conv_1",
                "title": "Test Chat",
                "messages": [
                    {"role": "human", "content": "Hi Grok"},
                    {"role": "grok", "content": "Hello!"},
                ],
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            convs = parse_grok_json(f.name)
        os.unlink(f.name)

        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["source"], "grok")
        self.assertEqual(convs[0]["messages"][0]["role"], "user")
        self.assertEqual(convs[0]["messages"][1]["role"], "assistant")

    def test_parse_flat_messages(self):
        """Test parsing Grok JSON with flat message records."""
        data = [
            {"conversation_id": "c1", "role": "human", "content": "Question", "timestamp": "2025-01-01T00:00:00Z"},
            {"conversation_id": "c1", "role": "grok", "content": "Answer", "timestamp": "2025-01-01T00:00:01Z"},
            {"conversation_id": "c2", "role": "user", "content": "Hello", "timestamp": "2025-01-01T00:01:00Z"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            convs = parse_grok_json(f.name)
        os.unlink(f.name)

        self.assertEqual(len(convs), 2)
        c1 = [c for c in convs if c["id"] == "c1"][0]
        self.assertEqual(len(c1["messages"]), 2)
        self.assertEqual(c1["messages"][0]["role"], "user")
        self.assertEqual(c1["messages"][1]["role"], "assistant")

    def test_find_grok_data_single_file(self):
        """Test that find_grok_data accepts a single JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([], f)
            f.flush()
            found = find_grok_data(f.name)
        os.unlink(f.name)

        self.assertIn("conversations", found)
        self.assertEqual(len(found["conversations"]), 1)

    def test_find_grok_data_directory(self):
        """Test that find_grok_data walks a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "prod-grok-backend.json"), "w") as f:
                json.dump([], f)
            found = find_grok_data(tmpdir)
            self.assertIn("conversations", found)


class TestGeminiTextParser(unittest.TestCase):
    def test_detect_turn_markers(self):
        text = "You\nHello\nGemini\nHi there\n"
        markers = _detect_turn_markers(text)
        self.assertEqual(len(markers), 2)
        self.assertEqual(markers[0][2], "user")
        self.assertEqual(markers[1][2], "assistant")

    def test_parse_simple_conversation(self):
        text = "You\nWhat is Python?\nGemini\nPython is a programming language.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            f.flush()
            convs = parse_gemini_text_file(f.name)
        os.unlink(f.name)

        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["source"], "gemini")
        self.assertEqual(len(convs[0]["messages"]), 2)
        self.assertEqual(convs[0]["messages"][0]["role"], "user")
        self.assertEqual(convs[0]["messages"][0]["content"], "What is Python?")
        self.assertEqual(convs[0]["messages"][1]["role"], "assistant")

    def test_parse_multiple_conversations(self):
        text = (
            "You\nFirst question\nGemini\nFirst answer\n"
            "---\n"
            "You\nSecond question\nGemini\nSecond answer\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            f.flush()
            convs = parse_gemini_text_file(f.name)
        os.unlink(f.name)

        self.assertEqual(len(convs), 2)

    def test_split_into_conversations(self):
        text = "part one\n---\npart two\n===\npart three"
        chunks = _split_into_conversations(text)
        self.assertEqual(len(chunks), 3)

    def test_find_gemini_text_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["chat1.txt", "chat2.txt", "notes.md"]:
                with open(os.path.join(tmpdir, name), "w") as f:
                    f.write("test")
            files = find_gemini_text_files(tmpdir)
            self.assertEqual(len(files), 2)
            self.assertTrue(all(f.endswith(".txt") for f in files))

    def test_parse_all_gemini_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            text = "You\nHi\nGemini\nHello!\n"
            with open(os.path.join(tmpdir, "chat.txt"), "w") as f:
                f.write(text)

            convs = parse_all_gemini_text([tmpdir])
            self.assertEqual(len(convs), 1)
            self.assertEqual(convs[0]["source"], "gemini")

    def test_bold_markers(self):
        """Test that **You** and **Gemini** markers work."""
        text = "**You**\nHello\n**Gemini**\nHi there\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            f.flush()
            convs = parse_gemini_text_file(f.name)
        os.unlink(f.name)

        self.assertEqual(len(convs), 1)
        self.assertEqual(len(convs[0]["messages"]), 2)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("")
            f.flush()
            convs = parse_gemini_text_file(f.name)
        os.unlink(f.name)
        self.assertEqual(len(convs), 0)


if __name__ == "__main__":
    unittest.main()
