#!/usr/bin/env python3
"""Copy an agent's last reply in herdr to the clipboard.

Usage:
  copy_last.py copy [PANE_ID]   copy the reply of the agent in PANE_ID (default: focused pane)
  copy_last.py print [PANE_ID]  print the reply instead of copying it
  copy_last.py open-picker      open the picker popup
  copy_last.py picker           run the picker (inside the popup)

Claude Code, Codex and Pi replies come from the agent's own conversation file, so
the copy is the exact Markdown the agent wrote. Other agents fall back to the
recent terminal text herdr keeps for the pane.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import textwrap

HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
PLUGIN_ID = os.environ.get("HERDR_PLUGIN_ID") or "danemarguglio.copy-last"
SCREEN_LINES = 200


class CopyError(Exception):
    pass


# --- herdr -------------------------------------------------------------------


def herdr(*args):
    proc = subprocess.run([HERDR, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise CopyError((proc.stderr or proc.stdout).strip() or f"herdr {args[0]} failed")
    return proc.stdout


def herdr_json(*args):
    return json.loads(herdr(*args))["result"]


def list_agents():
    return herdr_json("agent", "list")["agents"]


def get_agent(pane_id):
    try:
        return herdr_json("agent", "get", pane_id)["agent"]
    except CopyError:
        raise CopyError(f"No agent in pane {pane_id}")


def focused_pane_id():
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
        context = json.loads(os.environ.get("HERDR_PLUGIN_CONTEXT_JSON") or "{}")
        pane_id = context.get("focused_pane_id")
    if not pane_id:
        raise CopyError("No focused pane")
    return pane_id


def notify(title, body=None):
    args = ["notification", "show", title]
    if body:
        args += ["--body", body]
    try:
        herdr(*args)
    except (CopyError, OSError):
        pass


def agent_label(agent):
    title = agent.get("terminal_title_stripped") or agent.get("pane_id")
    return f"{agent.get('agent', 'agent')} · {title}"


# --- transcripts -------------------------------------------------------------


def read_jsonl(path):
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def text_blocks(content, kinds):
    if isinstance(content, str):
        return [content] if content.strip() else []
    return [
        block["text"]
        for block in content or []
        if isinstance(block, dict) and block.get("type") in kinds and (block.get("text") or "").strip()
    ]


def last_claude_reply(entries):
    # One API response is split across entries that share message.id. The reply is
    # the text of the last response that contained any text.
    reply, reply_id = [], object()
    for entry in entries:
        message = entry.get("message") or {}
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        if message.get("model") == "<synthetic>":
            continue
        texts = text_blocks(message.get("content"), {"text"})
        if not texts:
            continue
        message_id = message.get("id")
        if message_id is None or message_id != reply_id:
            reply, reply_id = [], message_id
        reply.extend(texts)
    return "\n\n".join(reply)


def last_codex_reply(entries):
    reply = []
    for entry in entries:
        payload = entry.get("payload") or {}
        if entry.get("type") != "response_item" or payload.get("type") != "message":
            continue
        if payload.get("role") != "assistant":
            continue
        texts = text_blocks(payload.get("content"), {"output_text"})
        if texts:
            reply = texts
    return "\n\n".join(reply)


def last_pi_reply(entries):
    reply = []
    for entry in entries:
        message = entry.get("message") or {}
        if entry.get("type") != "message" or message.get("role") != "assistant":
            continue
        texts = text_blocks(message.get("content"), {"text"})
        if texts:
            reply = texts
    return "\n\n".join(reply)


def newest(paths):
    paths = [p for p in paths if os.path.isfile(p)]
    return max(paths, key=os.path.getmtime) if paths else None


def home(env_var, default):
    return os.path.expanduser(os.environ.get(env_var) or default)


def find_transcript(agent):
    kind = agent.get("agent")
    session = agent.get("agent_session") or {}
    session_id = session.get("value") or ""
    if session_id and os.path.isfile(session_id):
        return session_id
    if kind == "claude" and session_id:
        return newest(glob.glob(os.path.join(home("CLAUDE_CONFIG_DIR", "~/.claude"), "projects", "*", f"{session_id}.jsonl")))
    if kind == "codex" and session_id:
        return newest(glob.glob(os.path.join(home("CODEX_HOME", "~/.codex"), "sessions", "*", "*", "*", f"rollout-*{session_id}.jsonl")))
    if kind == "pi":
        cwd = agent.get("cwd") or ""
        folder = os.path.join(home("PI_CODING_AGENT_DIR", "~/.pi/agent"), "sessions", "--" + cwd.strip("/").replace("/", "-") + "--")
        # Without a session id from herdr, the newest conversation in this folder is the best guess.
        return newest(glob.glob(os.path.join(folder, f"*_{session_id}.jsonl" if session_id else "*.jsonl")))
    return None


READERS = {"claude": last_claude_reply, "codex": last_codex_reply, "pi": last_pi_reply}


def last_reply(agent):
    """Return (text, source) where source is "transcript" or "screen"."""
    reader = READERS.get(agent.get("agent"))
    path = find_transcript(agent) if reader else None
    if path:
        text = reader(read_jsonl(path)).strip()
        if text:
            return text, "transcript"
    text = herdr("agent", "read", agent["pane_id"], "--source", "recent-unwrapped", "--lines", str(SCREEN_LINES))
    return text.strip(), "screen"


# --- clipboard ---------------------------------------------------------------


def copy_to_clipboard(text):
    env = dict(os.environ, LC_CTYPE="UTF-8", LANG=os.environ.get("LANG") or "en_US.UTF-8")
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), env=env, check=True, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except (subprocess.SubprocessError, OSError):
            continue
    raise CopyError("No clipboard tool worked (tried pbcopy, wl-copy, xclip, xsel)")


def copy_agent(agent):
    text, source = last_reply(agent)
    if not text:
        raise CopyError(f"{agent_label(agent)} has no reply yet")
    copy_to_clipboard(text)
    lines = text.count("\n") + 1
    note = "" if source == "transcript" else " (screen text, no transcript)"
    notify("Copied last reply", f"{agent_label(agent)} · {lines} lines{note}")
    return text


# --- picker ------------------------------------------------------------------

STATUS_STYLE = {
    # status: (symbol, curses color)
    "working": ("◐", "yellow"),
    "blocked": ("▲", "red"),
    "done": ("●", "blue"),
    "idle": ("●", "green"),
}


def location_labels():
    """Map pane ids' workspace and tab ids to their labels, e.g. "wiki/tonie"."""
    try:
        workspaces = {w["workspace_id"]: w.get("label") or w["workspace_id"] for w in herdr_json("workspace", "list")["workspaces"]}
        tabs = {t["tab_id"]: t.get("label") or str(t.get("number", "")) for t in herdr_json("tab", "list")["tabs"]}
    except (CopyError, OSError, ValueError, KeyError):
        return lambda agent: agent.get("pane_id", "")
    return lambda agent: f"{workspaces.get(agent.get('workspace_id'), '?')}/{tabs.get(agent.get('tab_id'), '?')}"


def wrap(text, width):
    lines = []
    for line in text.expandtabs(4).splitlines() or [""]:
        indent = line[:len(line) - len(line.lstrip())]
        lines.extend(textwrap.wrap(line.lstrip(), width, initial_indent=indent, subsequent_indent=indent,
                                   replace_whitespace=False) or [""])
    return lines


class Picker:
    HELP = "↑↓ jk move · 1-9 jump · enter/y copy · pgup/pgdn scroll · esc close"

    def __init__(self, screen, agents, location):
        import curses

        self.curses = curses
        self.screen = screen
        self.agents = agents
        self.location = location
        self.index = next((i for i, a in enumerate(agents) if a.get("focused")), 0)
        self.scroll = 0
        self.previews = {}
        self.colors = {}
        curses.curs_set(0)
        if curses.has_colors():
            curses.use_default_colors()
            for n, (name, value) in enumerate(
                [("yellow", curses.COLOR_YELLOW), ("red", curses.COLOR_RED), ("blue", curses.COLOR_BLUE),
                 ("green", curses.COLOR_GREEN), ("dim", curses.COLOR_WHITE)], start=1):
                curses.init_pair(n, value, -1)
                self.colors[name] = curses.color_pair(n)

    def preview(self, agent):
        key = agent["pane_id"]
        if key not in self.previews:
            try:
                text, source = last_reply(agent)
                if not text:
                    text = "(no reply yet)"
                elif source == "screen":
                    text = "(no conversation file — showing recent screen text)\n\n" + text
            except (CopyError, OSError) as err:
                text = f"(could not read reply: {err})"
            self.previews[key] = text
        return self.previews[key]

    def put(self, y, x, text, attr=0):
        height, width = self.screen.getmaxyx()
        if 0 <= y < height and x < width - 1:
            try:
                self.screen.addnstr(y, x, text, width - 1 - x, attr)
            except self.curses.error:
                pass

    def draw(self):
        curses = self.curses
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 8 or width < 30:
            self.put(0, 0, "Popup too small")
            self.screen.refresh()
            return
        count = f"{len(self.agents)} agent{'s' * (len(self.agents) != 1)}"
        self.put(0, 1, "Copy last reply", curses.A_BOLD)
        self.put(0, max(1, width - len(count) - 2), count, self.colors.get("dim", 0))

        list_height = min(len(self.agents), max(3, (height - 5) // 3))
        top = max(0, min(self.index - list_height + 1, len(self.agents) - list_height))
        place_width = max(len(self.location(a)) for a in self.agents)
        for row, agent in enumerate(self.agents[top:top + list_height]):
            i = top + row
            selected = i == self.index
            status = agent.get("agent_status") or "unknown"
            symbol, color = STATUS_STYLE.get(status, ("○", "dim"))
            base = curses.A_REVERSE if selected else 0
            y = row + 2
            self.put(y, 0, " " * (width - 1), base)
            self.put(y, 1, ("›" if selected else " ") + (f"{i + 1}" if i < 9 else " "), base | curses.A_BOLD)
            self.put(y, 4, symbol, base if selected else self.colors.get(color, 0))
            self.put(y, 6, f"{status:8} {self.location(agent):{place_width}}  {agent.get('agent', ''):7} "
                           f"{agent.get('terminal_title_stripped') or agent['pane_id']}", base)

        divider = list_height + 2
        self.put(divider, 0, "─" * (width - 1), self.colors.get("dim", 0))
        body_top, body_height = divider + 1, height - divider - 3
        lines = wrap(self.preview(self.agents[self.index]), width - 3)
        self.scroll = max(0, min(self.scroll, len(lines) - body_height))
        for row, line in enumerate(lines[self.scroll:self.scroll + body_height]):
            self.put(body_top + row, 1, line)
        self.put(height - 2, 0, "─" * (width - 1), self.colors.get("dim", 0))
        more = f" {self.scroll + 1}-{min(len(lines), self.scroll + body_height)}/{len(lines)} " if len(lines) > body_height else ""
        self.put(height - 1, 1, self.HELP, self.colors.get("dim", 0))
        self.put(height - 2, max(1, width - len(more) - 2), more, self.colors.get("dim", 0))
        self.screen.refresh()

    def move(self, index):
        self.index = index % len(self.agents)
        self.scroll = 0

    def run(self):
        curses = self.curses
        while True:
            self.draw()
            key = self.screen.getch()
            page = max(1, self.screen.getmaxyx()[0] // 2)
            if key in (curses.KEY_UP, ord("k")):
                self.move(self.index - 1)
            elif key in (curses.KEY_DOWN, ord("j"), 9):
                self.move(self.index + 1)
            elif key in (curses.KEY_HOME, ord("g")):
                self.move(0)
            elif key in (curses.KEY_END, ord("G")):
                self.move(len(self.agents) - 1)
            elif ord("1") <= key <= ord("9") and key - ord("1") < len(self.agents):
                self.move(key - ord("1"))
            elif key in (curses.KEY_NPAGE, 4, ord(" ")):  # pgdn, ctrl-d, space
                self.scroll += page
            elif key in (curses.KEY_PPAGE, 21):  # pgup, ctrl-u
                self.scroll = max(0, self.scroll - page)
            elif key in (curses.KEY_ENTER, 10, 13, ord("y")):
                return self.agents[self.index]
            elif key in (27, ord("q"), 3):
                return None


def run_picker():
    agents = list_agents()
    if not agents:
        notify("No agents to copy from")
        return
    location = location_labels()
    os.environ.setdefault("ESCDELAY", "25")
    import curses

    chosen = curses.wrapper(lambda screen: Picker(screen, agents, location).run())
    if chosen:
        copy_agent(chosen)


# --- main --------------------------------------------------------------------


def main(argv):
    command = argv[1] if len(argv) > 1 else "copy"
    try:
        if command in ("copy", "print"):
            agent = get_agent(argv[2] if len(argv) > 2 else focused_pane_id())
            if command == "print":
                print(last_reply(agent)[0])
            else:
                copy_agent(agent)
        elif command == "open-picker":
            herdr("plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", "picker")
        elif command == "picker":
            run_picker()
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except CopyError as err:
        notify("Copy failed", str(err))
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
