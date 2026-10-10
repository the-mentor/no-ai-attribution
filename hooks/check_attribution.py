#!/usr/bin/env python3
"""PreToolUse hook: block git / gh commands and GitHub MCP write tools whose
message content mentions Claude, Anthropic, or AI-assistance attribution, git
commands that would record an AI assistant as author or committer, and pushes
of commits that already carry either.
"""
import json
import os
import re
import shlex
import subprocess
import sys

# A git command that writes commits or tags, so records an author/committer.
# Anything but a command separator may sit between the program and its
# subcommand (e.g. `git -c user.name=x commit`).
GIT_WRITE = re.compile(
    r"\bgit\b[^|;&\n]*?\s(?:commit|merge|tag|notes|revert|cherry-pick|rebase|am)\b"
)
# A git or gh write command.
COMMIT_LIKE = re.compile(
    GIT_WRITE.pattern
    + r"|\bgh\b[^|;&\n]*?\s(?:(?:pr|issue)\s+(?:create|edit|comment|review|merge)"
    r"|release\s+(?:create|edit)|api)\b"
)
GIT_PUSH = re.compile(r"\bgit\b[^|;&\n]*?\spush\b")
ATTRIBUTION = re.compile(
    # Agent names only count as a co-author trailer, so "fix Cursor bug" passes.
    r"co-authored-by:\s*(?:claude|codex|copilot|cursor|gemini|aider)\b"
    r"|\bcopilot(?:\[bot\])?@users\.noreply\.github\.com"
    r"|\bcopilot@github\.com"
    r"|\bcursoragent@cursor\.com"
    r"|\bgemini-code-assist\[bot\]"
    r"|noreply@aider\.chat"
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
AGENTS = r"(?:claude|codex|copilot|cursor|gemini|aider)"
# A git identity that is an agent's: its whole name is an agent's name ("Claude",
# "Cursor Agent"; a person called "Claude Dupont" passes), an agent bot account
# ("copilot-swe-agent[bot]"), or aider's "Jane Doe (aider)" form. Agent noreply
# addresses are already in ATTRIBUTION.
AI_NAME = re.compile(
    rf"{AGENTS}(?:[ -]?(?:code|agent))?|[\w-]*{AGENTS}[\w-]*\[bot\]|.*\(aider\)",
    re.IGNORECASE,
)
AI_BOT_EMAIL = re.compile(rf"[\w-]*{AGENTS}[\w-]*\[bot\]@", re.IGNORECASE)
IDENTITY_KEYS = {
    "user.name", "user.email", "author.name", "author.email",
    "committer.name", "committer.email",
    "git_author_name", "git_author_email", "git_committer_name", "git_committer_email",
}
MAX_FILE_BYTES = 1_000_000


def tokenize(command):
    # punctuation_chars splits `;`, `&&`, `|` off paths (`-F msg.txt;`).
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return command.split()


def directories(tokens, cwd):
    """The working directory, then each one the command switches to with `cd`
    or `git -C`; the last is where its git command runs."""
    dirs = [cwd]
    for i, tok in enumerate(tokens[:-1]):
        if tok == "cd" or (tok == "-C" and "git" in tokens[:i]):
            dirs.append(os.path.join(dirs[-1], os.path.expanduser(tokens[i + 1])))
    return dirs


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


def git(directory, args, env=None):
    """stdout of a git command, or "" if it fails (not a repo, no identity)."""
    try:
        r = subprocess.run(
            ["git", *args], cwd=directory, env=env,
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def ai_identity(ident):
    """Whether an identity ("Name <email>", or just a name or email) is an
    agent's."""
    name = ident.split("<", 1)[0].strip()
    return bool(
        ATTRIBUTION.search(ident) or AI_BOT_EMAIL.search(ident)
        or (name and AI_NAME.fullmatch(name))
    )


def identities(command, cwd):
    """The author/committer identities a git write command will record: the
    ones it sets itself (`--author`, `-c user.name=`, `GIT_AUTHOR_NAME=`), and
    the ones git resolves from config and environment where it runs."""
    tokens = tokenize(command)
    found, config, env = [], [], dict(os.environ)
    has_author = False
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok == "--author" and nxt:
            found.append(nxt)
            has_author = True
        elif tok.startswith("--author="):
            found.append(tok.split("=", 1)[1])
            has_author = True
        elif "=" in tok:
            key, value = tok.split("=", 1)
            if key.lower() in IDENTITY_KEYS:
                found.append(value)
                if key.isupper():
                    env[key] = value
                elif tokens[i - 1 : i] == ["-c"]:
                    config += ["-c", tok]
    directory = directories(tokens, cwd)[-1]
    variables = ["GIT_COMMITTER_IDENT"] + ([] if has_author else ["GIT_AUTHOR_IDENT"])
    for var in variables:
        # Drop the trailing "<timestamp> <tz>".
        found.append(git(directory, [*config, "var", var], env).rsplit(">", 1)[0] + ">")
    return [i for i in found if i.strip("<> ")]


def unpushed_attribution(command, cwd):
    """The first commit on the current branch that no remote-tracking branch has
    yet and that carries attribution, as "<sha>: <what>", else None. A backstop
    for commits made where this hook can't see them."""
    directory = directories(tokenize(command), cwd)[-1]
    log = git(directory, [
        "log", "-n", "200", "--format=%h%x00%an <%ae>%x00%cn <%ce>%x00%B%x1e",
        "HEAD", "--not", "--remotes",
    ])
    for record in filter(str.strip, log.split("\x1e")):
        sha, author, committer, body = record.strip("\n").split("\0", 3)
        for ident in (author, committer):
            if ai_identity(ident):
                return f"{sha}: identity {ident}"
        if ATTRIBUTION.search(body):
            return f"{sha}: message"
    return None


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


def violation(data, args):
    """Why the tool call is blocked, or None to allow it."""
    text = text_to_check(data, args)
    if text and ATTRIBUTION.search(text):
        return (
            "Blocked: this command contains AI-assistant attribution (e.g. a "
            "Co-authored-by trailer or 'Generated with' footer), which is not "
            "allowed in commits, PRs, and issues. Remove the attribution and retry."
        )
    command = args.get("command", "") if isinstance(args, dict) else ""
    tool = str(data.get("tool_name") or data.get("toolName") or "")
    if not isinstance(command, str) or tool.startswith("mcp__"):
        return None
    cwd = str(data.get("cwd") or os.getcwd())
    if GIT_WRITE.search(command):
        for ident in identities(command, cwd):
            if ai_identity(ident):
                return (
                    f"Blocked: git would record an AI assistant ({ident}) as the "
                    "author or committer. Set the user's own identity with "
                    "`git config user.name` / `git config user.email` (ask the "
                    "user if you don't know it) and retry."
                )
    if GIT_PUSH.search(command):
        found = unpushed_attribution(command, cwd)
        if found:
            return (
                "Blocked: an unpushed commit carries AI-assistant attribution "
                f"({found}). Rewrite it with the user's identity and a clean "
                "message (e.g. `git commit --amend --reset-author`, or `git rebase "
                "--exec 'git commit --amend --no-edit --reset-author'` for several) "
                "and retry."
            )
    return None


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

    message = violation(data, args)
    if not message:
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
