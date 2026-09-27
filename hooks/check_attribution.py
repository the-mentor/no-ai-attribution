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
    r"|generated with \[?claude"
    r"|claude\.com/claude-code"
    r"|\banthropic\b"
    r"|\bclaude code\b"
    r"|noreply@anthropic\.com",
    re.IGNORECASE,
)


def main():
    data = json.load(sys.stdin)
    command = data.get("tool_input", {}).get("command", "")

    if not command or not COMMIT_LIKE.search(command):
        return 0

    if ATTRIBUTION.search(command):
        message = (
            "Blocked: this command mentions Claude/Anthropic attribution, which "
            "the user's global CLAUDE.md forbids in commits, PRs, and issues. "
            "Remove the attribution line/footer and retry."
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
