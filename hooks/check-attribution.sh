#!/bin/bash
# PreToolUse hook: block git commit / gh pr / gh issue commands whose
# message content mentions Claude, Anthropic, or AI-assistance attribution.
set -euo pipefail

input=$(cat)
command=$(echo "$input" | jq -r '.tool_input.command // empty')

if [ -z "$command" ]; then
  exit 0
fi

# Only scope this check to commands that write commit/PR/issue text.
if ! [[ "$command" =~ (git[[:space:]]+(-C[[:space:]]+[^[:space:]]+[[:space:]]+)?commit|gh[[:space:]]+pr[[:space:]]+(create|edit)|gh[[:space:]]+issue[[:space:]]+(create|edit)) ]]; then
  exit 0
fi

if echo "$command" | grep -qiE 'co-authored-by:[[:space:]]*claude|generated with \[?claude|claude\.com/claude-code|\banthropic\b|\bclaude code\b|noreply@anthropic\.com'; then
  echo '{"hookSpecificOutput": {"permissionDecision": "deny"}, "systemMessage": "Blocked: this command mentions Claude/Anthropic attribution, which the user'"'"'s global CLAUDE.md forbids in commits, PRs, and issues. Remove the attribution line/footer and retry."}' >&2
  exit 2
fi

exit 0
