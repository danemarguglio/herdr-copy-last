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


def run_picker():
    import curses

    agents = list_agents()
    if not agents:
        notify("No agents to copy from")
        return
    previews = {}

    def preview(agent):
        if agent["pane_id"] not in previews:
            try:
                previews[agent["pane_id"]] = last_reply(agent)[0] or "(no reply yet)"
            except (CopyError, OSError) as err:
                previews[agent["pane_id"]] = f"(error: {err})"
        return previews[agent["pane_id"]]

    def draw(screen, index):
        screen.erase()
        height, width = screen.getmaxyx()
        screen.addnstr(0, 0, "Copy last reply   ↑/↓ or j/k move · enter copy · esc close", width - 1, curses.A_BOLD)
        list_height = min(len(agents), max(3, height // 3))
        top = max(0, min(index - list_height + 1, len(agents) - list_height))
        for row, agent in enumerate(agents[top:top + list_height]):
            i = top + row
            line = f"{'›' if i == index else ' '} {agent.get('agent_status', '?'):8} {agent_label(agent)}  [{agent['pane_id']}]"
            screen.addnstr(row + 2, 0, line, width - 1, curses.A_REVERSE if i == index else 0)
        y = list_height + 3
        screen.hline(y, 0, curses.ACS_HLINE, width)
        for line in preview(agents[index]).splitlines():
            y += 1
            if y >= height:
                break
            screen.addnstr(y, 0, line.expandtabs(4), width - 1)
        screen.refresh()

    def loop(screen):
        curses.curs_set(0)
        index = next((i for i, a in enumerate(agents) if a.get("focused")), 0)
        while True:
            draw(screen, index)
            key = screen.getch()
            if key in (curses.KEY_UP, ord("k")):
                index = (index - 1) % len(agents)
            elif key in (curses.KEY_DOWN, ord("j")):
                index = (index + 1) % len(agents)
            elif key in (curses.KEY_ENTER, 10, 13):
                return agents[index]
            elif key in (27, ord("q")):
                return None

    os.environ.setdefault("ESCDELAY", "25")
    chosen = curses.wrapper(loop)
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
