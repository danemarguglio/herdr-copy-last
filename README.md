# herdr-copy-last

Copy an agent's last reply to your clipboard in [herdr](https://herdr.dev), with one key.

- **`prefix+y`** copies the last reply of the agent in the focused pane.
- **`prefix+shift+y`** opens a picker of every open agent with a preview of its last reply; `enter` copies it.

For Claude Code, Codex and Pi, the reply is read from the agent's own conversation file, so you get the exact Markdown the agent wrote: no terminal wrapping, no `⏺` markers, no tool output. For other agents it falls back to the recent terminal text herdr keeps for the pane, and the toast says so.

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

## Requirements

- herdr 0.9 or newer
- `python3` (standard library only)
- A clipboard tool: `pbcopy` (macOS), `wl-copy`, `xclip` or `xsel`

## What "last reply" means

| Agent | Source | Reply |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/*/<session>.jsonl` (honors `CLAUDE_CONFIG_DIR`) | Text of the last response that contained text; subagent and synthetic messages are skipped |
| Codex | `~/.codex/sessions/**/rollout-*<session>.jsonl` (honors `CODEX_HOME`) | Last assistant message |
| Pi | `~/.pi/agent/sessions/<cwd>/` (honors `PI_CODING_AGENT_DIR`) | Last assistant message with text |
| Anything else | `herdr agent read --source recent-unwrapped` | Last 200 lines of the pane |

herdr reports the session id for Claude Code and Codex. When it doesn't for Pi, the newest conversation in that folder is used, which can be the wrong one if two Pi agents share a directory.

## Command line

```sh
python3 copy_last.py print w1:p2   # print the reply of the agent in pane w1:p2
python3 copy_last.py copy w1:p2    # copy it
```

## License

MIT
