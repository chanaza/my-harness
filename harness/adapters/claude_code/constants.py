"""Names the Claude Code adapter installs. The harvester skips them: they are the engine's, not the user's."""

TOOL = "claude-code"
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "PreCompact", "SessionEnd")
HOOK_MARKER = "-m harness hook claude-code"
SKILL_NAME = "harness-save"
