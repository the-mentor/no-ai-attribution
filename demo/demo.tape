# Renders the demo with VHS (https://github.com/charmbracelet/vhs), from the repo root:
#   vhs demo/demo.tape
# Runs a real Claude Code session in a throwaway repo at /tmp/nai-demo, with this
# checkout's hook copied to the path-neutral /tmp/no-ai-attribution (so the hook's
# own block message doesn't print this machine's home directory) and loaded via
# --plugin-dir, every other installed plugin (plus any custom status line) disabled
# so only the hook's own output shows, and verbose tool output turned on so the
# block message renders in full (see demo/setup.sh for all of this). Claude Code's
# own default commit trailer trips the hook, so the block and retry are genuine,
# not scripted. One-time setup before recording: run `claude` by hand in
# /tmp/nai-demo and accept the folder-trust prompt, so it's saved and doesn't appear
# in the recording. VHS writes the GIF directly; no MP4 intermediate is needed.

Output demo/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 560
Set Framerate 12
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set WindowBar Colorful

Hide
Type "source demo/setup.sh" Enter
Sleep 500ms
Type "rm -rf /tmp/nai-demo && git init -q /tmp/nai-demo && cd /tmp/nai-demo && git config user.name dev && git config user.email dev@example.com && git commit -q --allow-empty -m init && echo fix > login.txt && git add login.txt" Enter
Sleep 500ms
Type "clear" Enter
Sleep 500ms
Show

Type "claude"
Enter
Sleep 6s

Type "commit the staged change"
Sleep 500ms Enter
Sleep 40s

Type "exit" Enter
Sleep 1.5s
Type "git log --format='%h %s%n%b'" Enter
Sleep 3s
