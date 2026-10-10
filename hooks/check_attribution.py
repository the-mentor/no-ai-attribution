#!/usr/bin/env python3
"""PreToolUse hook: block git / gh commands and GitHub MCP write tools whose
message content mentions Claude, Anthropic, or AI-assistance attribution, and
git commits that would record an AI agent as author or committer.
"""
import json
import os
import re
import shlex
import subprocess
import sys

# A git or gh write command. Anything but a command separator may sit between
# the program and its subcommand (e.g. `git -c user.name=x commit`).
GIT_WRITE = re.compile(
    r"\bgit\b[^|;&\n]*?\s(?:commit|merge|tag|notes|revert|cherry-pick|rebase|am)\b"
)
COMMIT_LIKE = re.compile(
    GIT_WRITE.pattern
    + r"|\bgh\b[^|;&\n]*?\s(?:(?:pr|issue)\s+(?:create|edit|comment|review|merge)"
    r"|release\s+(?:create|edit)|api)\b"
)
ATTRIBUTION = re.compile(
    # Agent names only count as a co-author trailer, so "fix Cursor bug" passes.
    r"co-authored-by:\s*(?:claude|codex|copilot|cursor|gemini|aider)\b"
    r"|\bcopilot(?:\[bot\])?@users\.noreply\.github\.com"
    r"|\bcopilot@github\.com"
    r"|\bcursoragent@cursor\.com"
    r"|\bgemini-code-assist\[bot\]"
    r"|noreply@aider\.chat"
    r"|generated (?:with|by) \[?claude"
    r"|generated (?:with|by) \[?codex"
    r"|claude\.com/claude-code"
    r"|\banthropic\b"
    r"|\bclaude code\b"
    r"|\bopenai codex\b"
    r"|noreply@anthropic\.com"
    r"|noreply@openai\.com",
    re.IGNORECASE,
)
# An author/committer identity ("Name <email>") that belongs to an agent: the
# name is just an agent (or its bot account), or the email is an agent address.
# Narrower than ATTRIBUTION so "Claude Dupont" or jane@anthropic.com still pass.
AGENT = r"(?:claude|codex|copilot|cursor|gemini|aider)"
AI_IDENTITY = re.compile(
    rf"^\s*{AGENT}(?:[ -]?agent)?\s*(?:<|$)"
    rf"|^\s*{AGENT}[\w-]*\[bot\]"
    r"|<[^>]*(?:noreply@anthropic\.com|noreply@openai\.com|noreply@aider\.chat"
    r"|cursoragent@cursor\.com|copilot@github\.com"
    rf"|\b{AGENT}[\w-]*(?:\[bot\])?@users\.noreply\.github\.com)>",
    re.IGNORECASE,
)
IDENTITY_ENV = re.compile(r"GIT_(?:AUTHOR|COMMITTER)_(?:NAME|EMAIL)=")
# Flags whose value is a file holding the message/body.
FILE_FLAGS = {"-F", "--file", "--body-file", "--notes-file", "--input", "-t", "--template"}
MCP_READ = {"get", "list", "read", "search"}
MAX_FILE_BYTES = 1_000_000


def tokenize(command):
    # punctuation_chars splits `;`, `&&`, `|` off paths (`-F msg.txt;`).
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return command.split()


def referenced_files(command, cwd):
    """(directory, path) pairs for the files the command reads its message from
    (`-F msg.txt`, `body=@file`). Tracks `cd` and `git -C` so relative paths
    resolve where the command actually runs."""
    tokens = tokenize(command)
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


def identities(command, cwd):
    """The author/committer identities a git command would record: any
    `--author`, plus what `git var` resolves from config and env in each
    directory the command runs in, with the command's own `-c user.*=` and
    `GIT_AUTHOR_*=` overrides applied."""
    tokens = tokenize(command)
    dirs, config, env, found = [cwd], [], dict(os.environ), []
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if nxt and (tok == "cd" or (tok == "-C" and "git" in tokens[:i])):
            dirs.append(os.path.join(dirs[-1], os.path.expanduser(nxt)))
        elif tok == "-c" and nxt.lower().startswith("user."):
            config += ["-c", nxt]
        elif IDENTITY_ENV.match(tok):
            key, value = tok.split("=", 1)
            env[key] = value
        elif tok == "--author":
            found.append(nxt)
        elif tok.startswith("--author="):
            found.append(tok.split("=", 1)[1])
    for d in dirs:
        for var in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
            try:
                out = subprocess.run(
                    ["git", *config, "var", var],
                    cwd=d, env=env, capture_output=True, text=True, timeout=3,
                ).stdout
            except (OSError, subprocess.SubprocessError):
                continue  # no git, no such directory, or too slow: can't tell, allow
            found.append(out.strip())
    return found


def ai_identity(data, args):
    """The agent identity a git write would record, or None."""
    command = args.get("command", "") if isinstance(args, dict) else ""
    if not isinstance(command, str) or not GIT_WRITE.search(command):
        return None
    cwd = str(data.get("cwd") or os.getcwd())
    return next((i for i in identities(command, cwd) if AI_IDENTITY.search(i)), None)


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
    if text and ATTRIBUTION.search(text):
        message = (
            "Blocked: this command contains AI-assistant attribution (e.g. a "
            "Co-authored-by trailer or 'Generated with' footer), which is not "
            "allowed in commits, PRs, and issues. Remove the attribution and retry."
        )
    elif ident := ai_identity(data, args):
        message = (
            f"Blocked: git would record an AI assistant as author or committer "
            f"({''.join(ident.partition('>')[:2])}). Set the user's own git identity (git config "
            f"user.name / user.email, or GIT_AUTHOR_* / GIT_COMMITTER_*) and retry."
        )
    else:
        return 0

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
