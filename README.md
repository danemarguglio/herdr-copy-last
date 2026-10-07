# herdr-copy-last

[![test](https://github.com/danemarguglio/herdr-copy-last/actions/workflows/test.yml/badge.svg)](https://github.com/danemarguglio/herdr-copy-last/actions/workflows/test.yml)

Copy an agent's last reply to your clipboard in [herdr](https://herdr.dev), with one key.

- **`prefix+y`** copies the last reply of the agent in the focused pane.
- **`prefix+shift+y`** opens a picker of every open agent, with a preview of each one's last reply.

You get the exact Markdown the agent wrote: no terminal line wrapping, no `⏺` markers, no tool output, no scrolling back to drag-select. A toast confirms which agent it came from.

```text
 Copy last reply                                                                  4 agents

 ›1 ● idle     api/tests     claude  Fix flaky cache test
  2 ◐ working  api/auth      codex   Migrate auth to OAuth 2.1
  3 ▲ blocked  docs/release  pi      Draft release notes
  4 ● done     docs/perf     claude  Benchmark parser
───────────────────────────────────────────────────────────────────────────────────────────
 The flaky test was a race: `cache.warm()` returns before the background fill finishes, so
 the first assertion sometimes reads an empty cache.

 Fixed by awaiting the fill in `conftest.py` and adding a regression test that runs the
 warm-up 200 times.

 - **Changed:** `tests/conftest.py`, `tests/test_cache.py`
 - **Verified:** full suite passes 50 runs in a row (was failing ~1 in 8)

 Want me to open a PR?

───────────────────────────────────────────────────────────────────────────────────────────
 ↑↓ jk move · 1-9 jump · enter/y copy · pgup/pgdn scroll · esc close
```

## Install

```sh
herdr plugin install danemarguglio/herdr-copy-last
```

Then add the keys to `~/.config/herdr/config.toml` and run `herdr server reload-config`:

```toml
[[keys.command]]
key = "prefix+y"
type = "plugin_action"
command = "danemarguglio.copy-last.copy"
description = "copy focused agent's last reply"

[[keys.command]]
key = "prefix+shift+y"
type = "plugin_action"
command = "danemarguglio.copy-last.pick"
description = "pick an agent, copy its last reply"
```

Pick other keys if those are taken.

## Picker keys

| Key | Does |
| --- | --- |
| `↑` `↓` / `j` `k` / `tab` | Move between agents |
| `1`–`9` | Jump to an agent |
| `g` / `G` | First / last agent |
| `pgdn` `space` `ctrl-d` / `pgup` `ctrl-u` | Scroll the preview |
| `enter` / `y` | Copy and close |
| `esc` / `q` | Close |

The picker opens on the focused agent, so `prefix+shift+y` then `enter` is the same as `prefix+y` with a look first.

## Where the reply comes from

| Agent | Source | Reply |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/*/<session>.jsonl` (honors `CLAUDE_CONFIG_DIR`) | Text of the last response that contained text. Subagents and synthetic messages are skipped |
| Codex | `~/.codex/sessions/**/rollout-*<session>.jsonl` (honors `CODEX_HOME`) | Last assistant message |
| Pi | `~/.pi/agent/sessions/<cwd>/` (honors `PI_CODING_AGENT_DIR`) | Last assistant message with text |
| Anything else | `herdr agent read --source recent-unwrapped` | Last 200 lines of the pane, flagged as screen text |

herdr reports the session id for Claude Code and Codex, so those are exact. For Pi it uses the newest conversation in that directory, which can be the wrong one if two Pi agents share a directory.

Replies are read from files on your machine and only go to your clipboard. Nothing is sent anywhere.

## Requirements

- herdr 0.9 or newer
- `python3` 3.9 or newer (standard library only)
- A clipboard tool: `pbcopy` (macOS), `wl-copy`, `xclip` or `xsel`

## Command line

```sh
python3 copy_last.py print w1:p2   # print the last reply of the agent in pane w1:p2
python3 copy_last.py copy w1:p2    # copy it
```

Pane ids come from `herdr agent list`.

## Development

```sh
herdr plugin link "$PWD"
python3 -m unittest discover -s tests
herdr plugin log list --plugin danemarguglio.copy-last --limit 5
```

## License

MIT
