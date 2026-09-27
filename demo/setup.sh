# Sourced by demo.tape (VHS can't parse the nested quotes in the wrapper below).
# Loads this checkout's hook via --plugin-dir and disables every other
# installed plugin so only no-ai-attribution's hook is active for the demo.
# Builds the disable list from `claude plugin list` at runtime rather than
# hardcoding it, since that list is specific to whoever runs the recording.
export DISABLE_AUTOUPDATER=1
export PS1='$ '

NAI_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Just .claude-plugin/ and hooks/ are copied to a path-neutral location,
# because the hook's block message prints its own script path, and that
# would otherwise be this machine's home dir.
NAI_CHECKOUT=/tmp/no-ai-attribution
rm -rf "$NAI_CHECKOUT"
mkdir -p "$NAI_CHECKOUT"
cp -R "$NAI_SOURCE/.claude-plugin" "$NAI_SOURCE/hooks" "$NAI_CHECKOUT/"
# statusLine is overridden with a no-op command (not set to null: the schema
# wants an object or nothing) so any custom status line (e.g. oh-my-posh) is
# blanked out for the recording, regardless of where it's configured.
NAI_SETTINGS=$(command claude plugin list 2>/dev/null | python3 -c '
import json, re, sys
ids = re.findall(r"^\s*\S+\s+(\S+@\S+)\s*$", sys.stdin.read(), re.MULTILINE)
enabled = {i: (i == "no-ai-attribution@no-ai-attribution") for i in ids}
settings = {"enabledPlugins": enabled, "statusLine": {"type": "command", "command": "true"}, "verbose": True}
print(json.dumps(settings))
')

# Unset so the recorded session doesn't inherit this session's
# CLAUDE_CODE_CHILD_SESSION marker (shown onscreen as a "Transcript saving is
# off" warning) and look like a nested Claude Code session. (Not stripping
# ANTHROPIC_BASE_URL/AUTH_TOKEN: on accounts that auth via an internal gateway
# instead of OAuth, those vars ARE the credentials, and removing them breaks
# auth entirely - confirmed by testing.)
claude() {
  # CLAUDE_CODE_DISABLE_AGENT_VIEW is re-set after stripping (it also matches
  # the CLAUDE* strip pattern above) to suppress the "N agent(s)" badge the
  # on-demand daemon shows for other Claude Code sessions on this machine.
  env $(env | grep -oE '^(CLAUDE[A-Z_]*|AI_AGENT)' | sed 's/^/-u /') \
    CLAUDE_CODE_DISABLE_AGENT_VIEW=1 \
    command claude --plugin-dir "$NAI_CHECKOUT" --settings "$NAI_SETTINGS" --allowedTools 'Bash(git:*)' "$@"
}
