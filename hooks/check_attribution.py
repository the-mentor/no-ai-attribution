#!/usr/bin/env python3
"""PreToolUse hook: block git / gh commands and GitHub MCP write tools whose
message content mentions Claude, Anthropic, or AI-assistance attribution.
"""
import json
import os
import re
import shlex
import sys

# A git or gh write command. Anything but a command separator may sit between
# the program and its subcommand (e.g. `git -c user.name=x commit`).
COMMIT_LIKE = re.compile(
    r"\bgit\b[^|;&\n]*?\s(?:commit|merge|tag|notes|revert|cherry-pick)\b"
    r"|\bgh\b[^|;&\n]*?\s(?:(?:pr|issue)\s+(?:create|edit|comment|review|merge)"
    r"|release\s+(?:create|edit)|api)\b"
)
ATTRIBUTION = re.compile(
    r"co-authored-by:\s*claude"
    r"|co-authored-by:\s*codex"
    r"|generated with \[?claude"
    r"|generated with \[?codex"
    r"|claude\.com/claude-code"
    r"|\banthropic\b"
    r"|\bclaude code\b"
    r"|\bopenai codex\b"
    r"|noreply@anthropic\.com"
    r"|noreply@openai\.com",
    re.IGNORECASE,
)
# Flags whose value is a file holding the message/body.
FILE_FLAGS = {"-F", "--file", "--body-file", "--notes-file", "--input", "-t", "--template"}
MCP_READ = {"get", "list", "read", "search"}
MAX_FILE_BYTES = 1_000_000


def referenced_files(command, cwd):
    """(directory, path) pairs for the files the command reads its message from
    (`-F msg.txt`, `body=@file`). Tracks `cd` and `git -C` so relative paths
    resolve where the command actually runs."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    dirs, found = [cwd], []
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if nxt and (tok == "cd" or (tok == "-C" and "git" in tokens[:i])):
            dirs.append(os.path.join(dirs[-1], os.path.expanduser(nxt)))
        if tok in FILE_FLAGS:
            path = nxt
        elif tok.startswith("--") and tok.split("=", 1)[0] in FILE_FLAGS:
            path = tok.split("=", 1)[1]
        elif "=@" in tok:
            path = tok.split("=@", 1)[1]
        else:
            continue
        if path and path != "-":
            found += [(d, path) for d in dirs]
    return found


def read(cwd, path):
    try:
        with open(os.path.join(cwd, os.path.expanduser(path)), errors="ignore") as f:
            return f.read(MAX_FILE_BYTES)
    except OSError:
        return ""


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def text_to_check(data, args):
    """The text to scan for attribution, or None if the tool call is not a write."""
    tool = str(data.get("tool_name") or data.get("toolName") or "")
    if tool.startswith("mcp__"):
        words = set(re.split(r"[_\W]+", tool.lower()))
        if "github" not in tool.lower() or words & MCP_READ:
            return None
        return "\n".join(strings(args))

    command = args.get("command", "") if isinstance(args, dict) else ""
    if not isinstance(command, str) or not COMMIT_LIKE.search(command):
        return None
    cwd = str(data.get("cwd") or os.getcwd())
    return "\n".join([command] + [read(d, p) for d, p in referenced_files(command, cwd)])


def main():
    data = json.load(sys.stdin)
    # Claude Code / Codex / Qoder send tool_input; Copilot CLI sends toolArgs
    # (possibly as a JSON string).
    args = data.get("tool_input") or data.get("toolArgs") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {"command": args}

    text = text_to_check(data, args)
    if not text or not ATTRIBUTION.search(text):
        return 0

    message = (
        "Blocked: this command mentions Claude/Anthropic/Codex attribution, "
        "which is not allowed in commits, PRs, and issues. Remove the "
        "attribution line/footer and retry."
    )
    if "toolArgs" in data:  # Copilot CLI reads the decision from stdout
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": message}))
    print(
        json.dumps(
            {
                "hookSpecificOutput": {"permissionDecision": "deny"},
                "systemMessage": message,
            }
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
