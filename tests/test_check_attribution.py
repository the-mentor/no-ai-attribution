import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "check_attribution.py"


def run(command, payload=None):
    payload = json.dumps(payload or {"tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, HOOK], input=payload, capture_output=True, text=True
    )


class CheckAttribution(unittest.TestCase):
    def test_blocks_attribution(self):
        for cmd in [
            'git commit -m "fix\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>"',
            'git commit -m "fix\n\nCo-authored-by: Codex <noreply@openai.com>"',
            'git -C /repo commit -m "Generated with Claude Code"',
            'gh pr create --title x --body "🤖 Generated with [Claude Code](https://claude.com/claude-code)"',
            'gh issue edit 3 --body "Generated with Codex"',
        ]:
            with self.subTest(cmd=cmd):
                r = run(cmd)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(
                    json.loads(r.stderr)["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                )

    def test_allows_clean_or_unrelated(self):
        for cmd in [
            'git commit -m "fix parser edge case"',
            'gh pr create --title x --body "adds tests"',
            "gh pr view 12",
            "echo Co-Authored-By: Claude",
            "",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(cmd).returncode, 0)

    def test_copilot_payload(self):
        bad = 'git commit -m "x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"'
        for args in ({"command": bad}, json.dumps({"command": bad})):
            with self.subTest(args=type(args).__name__):
                r = run(None, {"toolName": "bash", "toolArgs": args})
                self.assertEqual(r.returncode, 2)
                self.assertEqual(json.loads(r.stdout)["permissionDecision"], "deny")
        clean = {"toolName": "bash", "toolArgs": {"command": 'git commit -m "x"'}}
        self.assertEqual(run(None, clean).returncode, 0)

    def test_qoder_payload(self):
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "run_in_terminal",
            "tool_input": {"command": 'gh pr create --body "Generated with Claude Code"'},
        }
        self.assertEqual(run(None, payload).returncode, 2)

    def test_manifest_versions_match(self):
        versions = {
            p: json.loads((ROOT / p / "plugin.json").read_text())["version"]
            for p in (".claude-plugin", ".codex-plugin", ".github/plugin", ".qoder-plugin")
        }
        self.assertEqual(len(set(versions.values())), 1, versions)

    def test_hook_configs_point_at_script(self):
        for f in ("hooks.json", "copilot-hooks.json", "qoder-hooks.json"):
            with self.subTest(f=f):
                text = (ROOT / "hooks" / f).read_text()
                json.loads(text)
                self.assertIn("/hooks/check_attribution.py", text)


if __name__ == "__main__":
    unittest.main()
