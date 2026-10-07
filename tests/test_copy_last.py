import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import copy_last as c  # noqa: E402


def claude(message_id, *blocks, sidechain=False, model="claude-opus-5-5"):
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"id": message_id, "model": model, "content": list(blocks)}}


def text(t, kind="text"):
    return {"type": kind, "text": t}


TOOL = {"type": "tool_use", "name": "Bash", "input": {}}
USER = {"type": "user", "message": {"role": "user", "content": "hi"}}


class ClaudeTest(unittest.TestCase):
    def test_last_response_with_text(self):
        entries = [USER, claude("a", text("Checking.")), claude("a", TOOL),
                   {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
                   claude("b", {"type": "thinking", "thinking": "hmm"}), claude("b", text("Final answer."))]
        self.assertEqual(c.last_claude_reply(entries), "Final answer.")

    def test_joins_blocks_of_one_response(self):
        entries = [claude("a", text("old")), claude("b", text("one")), claude("b", TOOL), claude("b", text("two"))]
        self.assertEqual(c.last_claude_reply(entries), "one\n\ntwo")

    def test_trailing_tool_call_keeps_previous_text(self):
        entries = [claude("a", text("Reply.")), claude("b", TOOL)]
        self.assertEqual(c.last_claude_reply(entries), "Reply.")

    def test_skips_subagents_and_synthetic(self):
        entries = [claude("a", text("Real.")), claude("b", text("sub"), sidechain=True),
                   claude("c", text("No response requested."), model="<synthetic>")]
        self.assertEqual(c.last_claude_reply(entries), "Real.")

    def test_string_content_and_missing_ids(self):
        entries = [{"type": "assistant", "message": {"content": "first"}},
                   {"type": "assistant", "message": {"content": "second"}}]
        self.assertEqual(c.last_claude_reply(entries), "second")

    def test_empty(self):
        self.assertEqual(c.last_claude_reply([USER]), "")


class CodexTest(unittest.TestCase):
    def item(self, role, *texts, kind="output_text"):
        return {"type": "response_item", "payload": {"type": "message", "role": role,
                                                     "content": [text(t, kind) for t in texts]}}

    def test_last_assistant_message(self):
        entries = [self.item("user", "q", kind="input_text"), self.item("assistant", "Working on it."),
                   {"type": "response_item", "payload": {"type": "custom_tool_call"}},
                   self.item("assistant", "Done.", "Details.")]
        self.assertEqual(c.last_codex_reply(entries), "Done.\n\nDetails.")


class PiTest(unittest.TestCase):
    def msg(self, role, *blocks):
        return {"type": "message", "message": {"role": role, "content": list(blocks)}}

    def test_last_assistant_text(self):
        entries = [self.msg("user", text("q")), self.msg("assistant", text("Answer.")),
                   self.msg("assistant", {"type": "toolCall", "name": "bash"}),
                   self.msg("toolResult", text("(no output)"))]
        self.assertEqual(c.last_pi_reply(entries), "Answer.")


class FindTranscriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def touch(self, *parts):
        path = os.path.join(self.root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return path

    def test_claude(self):
        path = self.touch("claude", "projects", "-x", "abc.jsonl")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": os.path.join(self.root, "claude")}):
            agent = {"agent": "claude", "agent_session": {"value": "abc"}}
            self.assertEqual(c.find_transcript(agent), path)

    def test_codex(self):
        path = self.touch("codex", "sessions", "2026", "10", "07", "rollout-2026-10-07T01-00-00-abc.jsonl")
        with mock.patch.dict(os.environ, {"CODEX_HOME": os.path.join(self.root, "codex")}):
            agent = {"agent": "codex", "agent_session": {"value": "abc"}}
            self.assertEqual(c.find_transcript(agent), path)

    def test_pi_newest_in_cwd_folder(self):
        old = self.touch("pi", "sessions", "--home-me-repo--", "1_old.jsonl")
        new = self.touch("pi", "sessions", "--home-me-repo--", "2_new.jsonl")
        os.utime(old, (1, 1))
        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": os.path.join(self.root, "pi")}):
            self.assertEqual(c.find_transcript({"agent": "pi", "cwd": "/home/me/repo"}), new)

    def test_session_value_that_is_a_path(self):
        path = self.touch("anything.jsonl")
        agent = {"agent": "claude", "agent_session": {"kind": "path", "value": path}}
        self.assertEqual(c.find_transcript(agent), path)

    def test_unknown_agent(self):
        self.assertIsNone(c.find_transcript({"agent": "mystery"}))


class LastReplyTest(unittest.TestCase):
    def test_transcript(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps(claude("a", text("Hello ✓"))) + "\nnot json\n")
        self.addCleanup(os.unlink, f.name)
        agent = {"agent": "claude", "pane_id": "w1:p1", "agent_session": {"value": f.name}}
        self.assertEqual(c.last_reply(agent), ("Hello ✓", "transcript"))

    def test_falls_back_to_screen(self):
        with mock.patch.object(c, "herdr", return_value="screen text\n") as herdr:
            self.assertEqual(c.last_reply({"agent": "mystery", "pane_id": "w1:p1"}), ("screen text", "screen"))
        self.assertEqual(herdr.call_args[0][:3], ("agent", "read", "w1:p1"))


class ClipboardTest(unittest.TestCase):
    def test_no_tool(self):
        with mock.patch.object(c.shutil, "which", return_value=None):
            with self.assertRaises(c.CopyError):
                c.copy_to_clipboard("x")

    def test_falls_through_failed_tool(self):
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd[0])
            if cmd[0] == "pbcopy":
                raise c.subprocess.CalledProcessError(1, cmd)
            self.assertEqual(kwargs["input"], "héllo".encode("utf-8"))

        with mock.patch.object(c.shutil, "which", return_value="/bin/x"), mock.patch.object(c.subprocess, "run", run):
            c.copy_to_clipboard("héllo")
        self.assertEqual(calls, ["pbcopy", "wl-copy"])


class WrapTest(unittest.TestCase):
    def test_keeps_blank_lines(self):
        self.assertEqual(c.wrap("a\n\nb", 10), ["a", "", "b"])

    def test_wraps_long_lines(self):
        lines = c.wrap("word " * 10, 10)
        self.assertTrue(all(len(line) <= 10 and not line.startswith(" ") for line in lines))

    def test_keeps_indent(self):
        self.assertEqual(c.wrap("  - aaa bbb ccc", 10), ["  - aaa", "  bbb ccc"])


if __name__ == "__main__":
    unittest.main()
