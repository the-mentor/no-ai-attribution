# no-ai-attribution

Works with **Claude Code**, **OpenAI Codex CLI**, **GitHub Copilot CLI**, and **Qoder**. Blocks `git commit`,
`gh pr create/edit`, and `gh issue create/edit` commands whose message text
mentions Claude, Anthropic, Codex, or AI-assistance attribution (e.g.
`Co-Authored-By: Claude ...`, `Co-Authored-By: Codex ...`, "🤖 Generated
with Claude Code" / "Generated with Codex" footers).

## Why

Some orgs/individuals never want AI attribution in committed history or
published PRs/issues, but Claude Code's default behavior appends it unless
overridden. Relying on a CLAUDE.md rule alone means the assistant has to
remember to skip the default every single time. This plugin enforces it
deterministically via a `PreToolUse` hook, independent of any per-session
instructions.

## Requirements

- **Python 3** available as `python3` on your PATH (including the
  non-interactive shell your agent runs hooks in, e.g. for pyenv/Nix users).
  The hook script uses only the standard library, so there's nothing to
  `pip install`.

If `python3` is missing, the hook fails to run. Depending on the agent, that
either silently leaves commits unchecked (e.g. Claude Code, Qoder) or blocks
every shell command (Copilot CLI fails closed on hook errors).

## Install

**Claude Code** (send as two separate prompts):
```
/plugin marketplace add the-mentor/no-ai-attribution
/plugin install no-ai-attribution@no-ai-attribution
```
or for local testing:
```
claude --plugin-dir /path/to/no-ai-attribution
```

**Codex CLI:**
```bash
codex plugin marketplace add the-mentor/no-ai-attribution
codex plugin add no-ai-attribution@no-ai-attribution
```
Codex reuses the same `hooks/hooks.json` schema (and sets
`CLAUDE_PLUGIN_ROOT` for compatibility). Non-managed plugin hooks require a
one-time trust review in Codex (`/hooks`) before they run.

**GitHub Copilot CLI:**
```bash
copilot plugin marketplace add the-mentor/no-ai-attribution
copilot plugin install no-ai-attribution@no-ai-attribution
```
Uses `.github/plugin/plugin.json` and `hooks/copilot-hooks.json`.

**Qoder CLI:**
```bash
git clone https://github.com/the-mentor/no-ai-attribution
qoder plugins install ./no-ai-attribution
```
Uses `.qoder-plugin/plugin.json` and `hooks/qoder-hooks.json`.

## Test

```bash
python3 -m unittest discover -s tests
```

## How it works

A `PreToolUse` hook matches `Bash` tool calls and runs a Python script
(stdlib only). If the command looks like a git commit or a `gh pr`/`gh
issue` create/edit, and its text matches known attribution patterns, the
tool call is denied (exit code 2 + `permissionDecision: deny`) with a
message telling Claude to strip the attribution and retry.

Non-matching commands (anything that isn't a commit/PR/issue write) pass
through untouched.
