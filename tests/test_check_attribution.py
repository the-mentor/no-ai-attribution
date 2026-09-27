import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "check_attribution.py"


def run(command):
    payload = json.dumps({"tool_input": {"command": command}})
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

    def test_manifest_versions_match(self):
        versions = {
            p: json.loads((ROOT / p / "plugin.json").read_text())["version"]
            for p in (".claude-plugin", ".codex-plugin")
        }
        self.assertEqual(len(set(versions.values())), 1, versions)


if __name__ == "__main__":
    unittest.main()
