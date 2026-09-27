# no-ai-attribution

Blocks `git commit`, `gh pr create/edit`, and `gh issue create/edit` commands
whose message text mentions Claude, Anthropic, or AI-assistance attribution
(e.g. `Co-Authored-By: Claude ...`, "🤖 Generated with Claude Code" footers).

## Why

Some orgs/individuals never want AI attribution in committed history or
published PRs/issues, but Claude Code's default behavior appends it unless
overridden. Relying on a CLAUDE.md rule alone means the assistant has to
remember to skip the default every single time. This plugin enforces it
deterministically via a `PreToolUse` hook, independent of any per-session
instructions.

## Install

```
/plugin install no-ai-attribution
```

or for local testing:

```
cc --plugin-dir /path/to/no-ai-attribution
```

## How it works

A `PreToolUse` hook matches `Bash` tool calls. If the command looks like a
git commit or a `gh pr`/`gh issue` create/edit, and its text matches known
attribution patterns, the tool call is denied (exit code 2 +
`permissionDecision: deny`) with a message telling Claude to strip the
attribution and retry.

Non-matching commands (anything that isn't a commit/PR/issue write) pass
through untouched.
