import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "check_attribution.py"
TRAILER = "Co-Authored-By: " + "Claude <noreply@" + "anthropic.com>"
FOOTER = "Generated with " + "Claude Code"


def run(command, payload=None):
    payload = json.dumps(payload or {"tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, HOOK], input=payload, capture_output=True, text=True
    )


def run_tool(tool, args, cwd=None):
    payload = {"tool_name": tool, "tool_input": args}
    if cwd:
        payload["cwd"] = cwd
    return run(None, payload)


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

    def test_blocks_former_bypasses(self):
        for cmd in [
            f'git -c user.name=x commit -m "{TRAILER}"',
            f'git --no-pager commit -m "{TRAILER}"',
            f'cd repo && git commit -m "{TRAILER}"',
            f'git merge --no-ff -m "{TRAILER}" topic',
            f'git tag -a v1 -m "{FOOTER}"',
            f'gh pr comment 1 --body "{FOOTER}"',
            f'gh pr review 1 --approve --body "{FOOTER}"',
            f'gh release create v1 --notes "{FOOTER}"',
            f'gh api repos/o/r/pulls -f body="{FOOTER}"',
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run_tool("Bash", {"command": cmd}).returncode, 2)

    def test_reads_message_files(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "msg.txt").write_text(f"fix\n\n{TRAILER}\n")
            (Path(d) / "clean.md").write_text("adds tests\n")
            blocked = [
                "git commit -F msg.txt",
                "git commit --file=msg.txt",
                "gh pr create --title x --body-file msg.txt",
                "gh release create v1 --notes-file msg.txt",
                "gh api repos/o/r/issues -F body=@msg.txt",
            ]
            allowed = ["git commit -F clean.md", "git commit -F missing.txt"]
            for cmd in blocked:
                with self.subTest(cmd=cmd):
                    self.assertEqual(run_tool("Bash", {"command": cmd}, cwd=d).returncode, 2)
            for cmd in allowed:
                with self.subTest(cmd=cmd):
                    self.assertEqual(run_tool("Bash", {"command": cmd}, cwd=d).returncode, 0)

    def test_github_mcp_tools(self):
        blocked = [
            ("mcp__agentgateway__github_create_pull_request", {"title": "x", "body": FOOTER}),
            ("mcp__github__add_issue_comment", {"body": TRAILER}),
            ("mcp__agentgateway__github_push_files", {"message": f"x\n\n{TRAILER}", "files": []}),
            ("mcp__github__create_or_update_file", {"message": TRAILER, "content": "x"}),
        ]
        allowed = [
            ("mcp__agentgateway__github_create_pull_request", {"title": "x", "body": "adds tests"}),
            ("mcp__agentgateway__github_get_file_contents", {"path": "README.md", "owner": "anthropic"}),
            ("mcp__agentgateway__github_search_code", {"query": FOOTER}),
            ("mcp__agentgateway__github_pull_request_read", {"method": "get", "body": FOOTER}),
            ("mcp__slack__send_message", {"text": FOOTER}),
        ]
        for tool, args in blocked:
            with self.subTest(tool=tool):
                self.assertEqual(run_tool(tool, args).returncode, 2)
        for tool, args in allowed:
            with self.subTest(tool=tool):
                self.assertEqual(run_tool(tool, args).returncode, 0)

    def test_ignores_reads_and_pipes(self):
        for cmd in [
            "gh api repos/o/r/pulls",
            "git log --grep=Claude",
            'cat README.md | grep "Claude Code"',
            "grep -r anthropic . | head",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run_tool("Bash", {"command": cmd}).returncode, 0)

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
