# no-ai-attribution

Works with **Claude Code**, **OpenAI Codex CLI**, **GitHub Copilot CLI**, and **Qoder**. Blocks
git commits, merges, and tags, `gh pr`/`gh issue` create/edit/comment/review,
`gh release create/edit`, `gh api` calls, and GitHub MCP write tools whose
text mentions Claude, Anthropic, Codex, or AI-assistance attribution (e.g.
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

**Claude Code** — run these one at a time, as two separate prompts:

1. Add the marketplace:
   ```
   /plugin marketplace add the-mentor/no-ai-attribution
   ```
2. Install the plugin:
   ```
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

A `PreToolUse` hook runs a Python script (stdlib only) on shell commands and
on GitHub MCP tool calls. It checks:

- **Shell commands** that write to git or GitHub: `git commit`, `merge`,
  `tag`, `notes`, `revert`, `cherry-pick` (including with options such as
  `git -c ... commit`), and `gh pr`/`issue` create/edit/comment/review/merge,
  `gh release create/edit`, and `gh api`. Message files passed with `-F`,
  `--file`, `--body-file`, `--notes-file`, or `field=@file` are read too.
- **GitHub MCP write tools** (any `mcp__*github*` tool that isn't a
  get/list/read/search): every string argument, such as `title`, `body`, or
  `message`.

If the text matches known attribution patterns, the call is denied (exit
code 2 + `permissionDecision: deny`) with a message telling the agent to
strip the attribution and retry. Everything else passes through untouched.

The whole command line is scanned, so an attribution footer anywhere in a
chained command (e.g. after `&&`) blocks the git write it's chained to.

On Copilot CLI only shell commands are checked; MCP tools aren't matched.

