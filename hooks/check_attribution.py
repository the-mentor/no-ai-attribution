#!/usr/bin/env python3
"""PreToolUse hook: block git commit / gh pr / gh issue commands whose
message content mentions Claude, Anthropic, or AI-assistance attribution.
"""
import json
import re
import sys

COMMIT_LIKE = re.compile(
    r"(git\s+(-C\s+\S+\s+)?commit|gh\s+pr\s+(create|edit)|gh\s+issue\s+(create|edit))"
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


def main():
    data = json.load(sys.stdin)
    command = data.get("tool_input", {}).get("command", "")

    if not command or not COMMIT_LIKE.search(command):
        return 0

    if ATTRIBUTION.search(command):
        message = (
            "Blocked: this command mentions Claude/Anthropic/Codex attribution, "
            "which is not allowed in commits, PRs, and issues. Remove the "
            "attribution line/footer and retry."
        )
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
