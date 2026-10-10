import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "check_attribution.py"
TRAILER = "Co-Authored-By: " + "Claude <noreply@" + "anthropic.com>"
FOOTER = "Generated with " + "Claude Code"
AI_EMAIL = "noreply@" + "anthropic.com"

# Git config the hook sees: a human identity, whatever the machine running the
# tests is configured with (an agent's sandbox may well have an AI identity).
_home = tempfile.mkdtemp()
GITCONFIG = Path(_home) / "gitconfig"
GITCONFIG.write_text("[user]\n\tname = Test Human\n\temail = human@example.com\n")
ENV = {
    k: v for k, v in os.environ.items()
    if not k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_", "GIT_CONFIG"))
}
ENV.update(GIT_CONFIG_GLOBAL=str(GITCONFIG), GIT_CONFIG_NOSYSTEM="1")


def run(command, payload=None, env=None):
    payload = json.dumps(payload or {"tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, HOOK], input=payload, capture_output=True, text=True,
        env={**ENV, **(env or {})},
    )


def run_tool(tool, args, cwd=None, env=None):
    payload = {"tool_name": tool, "tool_input": args}
    if cwd:
        payload["cwd"] = cwd
    return run(None, payload, env)


def git(directory, *args, env=None):
    subprocess.run(
        ["git", *args], cwd=directory, check=True, capture_output=True,
        env={**ENV, **(env or {})},
    )


def repo(directory, name="Test Human", email="human@example.com"):
    git(os.path.dirname(directory), "init", "-q", "-b", "main", directory)
    git(directory, "config", "user.name", name)
    git(directory, "config", "user.email", email)
    return directory


def commit(directory, message="change", env=None):
    path = Path(directory) / "file.txt"
    path.write_text(path.read_text() + "x" if path.exists() else "x")
    git(directory, "add", "file.txt")
    git(directory, "commit", "-q", "-m", message, env=env)


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
            # The file only exists in the directory the command switches to.
            sub = Path(d) / "sub"
            sub.mkdir()
            (sub / "only-here.txt").write_text(f"fix\n\n{TRAILER}\n")
            blocked += [
                f"cd {sub} && git commit -F only-here.txt",
                "cd sub && git commit -F only-here.txt",
                f"git -C {sub} commit -F only-here.txt",
                f"cd {d} && cd sub && git commit -F only-here.txt",
                # Shell separators glued to the path.
                "git commit -F msg.txt; echo done",
                "git commit -F msg.txt&& echo done",
                "git commit --file=msg.txt|cat",
                "gh pr create --title x --body-file msg.txt;",
                f"cd {sub};git commit -F only-here.txt",
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

    def test_blocks_other_agents(self):
        cab = "Co-authored-by: "
        for trailer in [
            # Copilot CLI / SDK / GitHub Desktop
            cab + "Copilot <223556219+Copilot@users.noreply" + ".github.com>",
            # VS Code Copilot
            cab + "Copilot <copilot@" + "github.com>",
            # Copilot coding agent
            cab + "Copilot <198982749+Copilot[bot]@users.noreply" + ".github.com>",
            # Cursor
            cab + "Cursor <cursoragent@" + "cursor.com>",
            # Gemini
            cab + "gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>",
            cab + "Gemini <gemini@google.com>",
            # Aider (opt-in trailer)
            cab + "aider (gpt-4o) <noreply@aider.chat>",
            # Bare addresses, lower case, and extra spaces
            "cursoragent@" + "cursor.com",
            "co-authored-by:   " + "copilot",
        ]:
            with self.subTest(trailer=trailer):
                cmd = f'git commit -m "fix" -m "{trailer}"'
                self.assertEqual(run_tool("Bash", {"command": cmd}).returncode, 2)

    def test_allows_agent_names_in_normal_messages(self):
        for msg in [
            "fix Cursor keybinding",
            "bump gemini SDK to 2.0",
            "document the Copilot integration",
            "add aider config example",
            "Co-authored-by: Jane Doe <jane@example.com>",
            "Co-authored-by: Copilotta Smith <c.smith@example.com>",
        ]:
            with self.subTest(msg=msg):
                cmd = f'git commit -m "{msg}"'
                self.assertEqual(run_tool("Bash", {"command": cmd}).returncode, 0)

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

    def test_readme_shows_the_real_block_message(self):
        r = run_tool("Bash", {"command": f'git commit -m "{TRAILER}"'})
        message = json.loads(r.stderr)["systemMessage"]
        readme = (ROOT / "README.md").read_text()
        shown = readme.split("⛔ ", 1)[1].split("\n```", 1)[0]
        self.assertEqual(" ".join(shown.split()), message)

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



class GitIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.human = repo(os.path.join(self.tmp.name, "human"))
        self.ai = repo(os.path.join(self.tmp.name, "ai"), "Claude", AI_EMAIL)

    def tearDown(self):
        self.tmp.cleanup()

    def assertBlocked(self, cmd, cwd, env=None):
        r = run_tool("Bash", {"command": cmd}, cwd=cwd, env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        return json.loads(r.stderr)["systemMessage"]

    def assertAllowed(self, cmd, cwd, env=None):
        r = run_tool("Bash", {"command": cmd}, cwd=cwd, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_blocks_ai_identity_from_config(self):
        for cmd in [
            'git commit -m "fix"',
            "git commit --amend --no-edit",
            "git merge topic",
            "git rebase main",
            "git am fix.patch",
            "git cherry-pick abc123",
            'git tag -a v1 -m "v1"',
        ]:
            with self.subTest(cmd=cmd):
                message = self.assertBlocked(cmd, self.ai)
                self.assertIn("author or committer", message)
                self.assertIn("git config user.name", message)

    def test_follows_cd_and_git_C(self):
        self.assertBlocked(f'cd {self.ai} && git commit -m "fix"', self.human)
        self.assertBlocked(f'git -C {self.ai} commit -m "fix"', self.human)
        self.assertAllowed(f'git -C {self.human} commit -m "fix"', self.ai)

    def test_blocks_ai_identity_from_environment(self):
        for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            with self.subTest(var=var):
                self.assertBlocked('git commit -m "fix"', self.human, {var: "Claude"})
        self.assertBlocked('git commit -m "fix"', self.human, {"GIT_AUTHOR_EMAIL": AI_EMAIL})

    def test_blocks_ai_identity_in_command(self):
        for cmd in [
            'git -c user.name=Claude commit -m "fix"',
            'GIT_AUTHOR_NAME=Claude git commit -m "fix"',
            'git commit --author="Claude <bot@example.com>" -m "fix"',
            'git commit --author "copilot-swe-agent[bot] <1+copilot-swe-agent[bot]@users.noreply.github.com>" -m "fix"',
            'git commit --author="Jane Doe (aider) <jane@example.com>" -m "fix"',
            'git commit --author="Cursor Agent <jane@example.com>" -m "fix"',
        ]:
            with self.subTest(cmd=cmd):
                self.assertBlocked(cmd, self.human)

    def test_command_can_override_an_ai_config(self):
        cmd = 'git -c user.name=Jane -c user.email=jane@example.com commit -m "fix"'
        self.assertAllowed(cmd, self.ai)
        # Only the author is overridden; the committer is still the AI.
        self.assertBlocked('git commit --author="Jane <jane@example.com>" -m "fix"', self.ai)

    def test_allows_human_identities(self):
        for name in ["Test Human", "Claude Dupont", "Gemini Lopez", "Codexa"]:
            with self.subTest(name=name):
                git(self.human, "config", "user.name", name)
                self.assertAllowed('git commit -m "fix"', self.human)

    def test_only_git_writes_are_checked(self):
        for cmd in ["git status", "git log", 'gh pr create --title x --body "adds tests"']:
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd, self.ai)

    def test_no_repo_or_no_identity(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        self.assertAllowed('git commit -m "fix"', plain)
        self.assertAllowed(
            'git commit -m "fix"', self.human, {"GIT_CONFIG_GLOBAL": os.devnull}
        )


class GitPush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        origin = os.path.join(self.tmp.name, "origin.git")
        git(self.tmp.name, "init", "-q", "--bare", origin)
        self.repo = repo(os.path.join(self.tmp.name, "work"))
        git(self.repo, "remote", "add", "origin", origin)
        commit(self.repo)
        git(self.repo, "push", "-q", "-u", "origin", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def push(self, cmd="git push"):
        return run_tool("Bash", {"command": cmd}, cwd=self.repo)

    def test_allows_clean_unpushed_commits(self):
        commit(self.repo, "fix parser")
        self.assertEqual(self.push().returncode, 0)

    def test_blocks_unpushed_ai_identity(self):
        ai = {"GIT_AUTHOR_NAME": "Claude", "GIT_AUTHOR_EMAIL": AI_EMAIL}
        commit(self.repo, "fix parser", env=ai)
        commit(self.repo, "later clean commit")
        for cmd in ["git push", "git push -u origin main", f"cd {self.repo} && git push"]:
            with self.subTest(cmd=cmd):
                r = self.push(cmd)
                self.assertEqual(r.returncode, 2)
                self.assertIn("unpushed commit", json.loads(r.stderr)["systemMessage"])

    def test_blocks_unpushed_attribution_trailer(self):
        commit(self.repo, f"fix parser\n\n{TRAILER}")
        self.assertEqual(self.push().returncode, 2)

    def test_ignores_commits_already_on_a_remote(self):
        commit(self.repo, f"old\n\n{TRAILER}")
        git(self.repo, "push", "-q")
        commit(self.repo, "fix parser")
        self.assertEqual(self.push().returncode, 0)


if __name__ == "__main__":
    unittest.main()
