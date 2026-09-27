# no-ai-attribution

Works with **Claude Code** and **OpenAI Codex CLI**. Blocks `git commit`,
`gh pr create/edit`, and `gh issue create/edit` commands whose message text
mentions Claude, Anthropic, or AI-assistance attribution (e.g.
`Co-Authored-By: Claude ...`, "🤖 Generated with Claude Code" footers).

## Why

Some orgs/individuals never want AI attribution in committed history or
published PRs/issues, but Claude Code's default behavior appends it unless
overridden. Relying on a CLAUDE.md rule alone means the assistant has to
remember to skip the default every single time. This plugin enforces it
deterministically via a `PreToolUse` hook, independent of any per-session
instructions.

## Install

**Claude Code:**
```
/plugin install no-ai-attribution
```
or for local testing:
```
cc --plugin-dir /path/to/no-ai-attribution
```

**Codex CLI:** install the plugin per Codex's plugin install flow, or point
Codex at this directory as a local plugin. Codex reuses the same
`hooks/hooks.json` schema (and sets `CLAUDE_PLUGIN_ROOT` for compatibility),
discovered via `.codex-plugin/plugin.json`. Note: non-managed plugin hooks
require a one-time trust review in Codex (`/hooks`) before they run.

## How it works

A `PreToolUse` hook matches `Bash` tool calls and runs a Python script
(stdlib only). If the command looks like a git commit or a `gh pr`/`gh
issue` create/edit, and its text matches known attribution patterns, the
tool call is denied (exit code 2 + `permissionDecision: deny`) with a
message telling Claude to strip the attribution and retry.

Non-matching commands (anything that isn't a commit/PR/issue write) pass
through untouched.
