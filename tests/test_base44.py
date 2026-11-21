"""Base44 Superagents: everything in its place, every item with this profile as its source,
no secrets, and conversations that keep growing although the API returns only the last 200."""

import json

from harness.adapters.base44 import Base44Adapter
from harness.adapters.base44.reader import Superagent
from harness.local import LocalHome
from harness.profiles import ProfileRegistry
from harness.repo import ContentRepo

FILES = {
    ".agents/.env": "HMS_PORTAL_PASSWORD=hunter2hunter2",
    ".agents/.memory/IDENTITY.md": "I am Koda.",
    ".agents/.memory/SOUL.md": "Calm and exact.",
    ".agents/.memory/USER.md": "Chana prefers Hebrew.",
    ".agents/rules/delete-requires-approval.md": "Never delete without approval.",
    ".agents/skills/hms-time-report/SKILL.md": "---\nname: hms-time-report\ndescription: Hours\n---\nRun it.",
    ".agents/skills/hms-time-report/scripts/run.sh": "node engine.js",
    ".agents/skills/hms-time-report/scripts/engine.js": (
        "const password = process.env.HMS_PORTAL_PASSWORD || '';"
    ),
    ".agents/mcps/config.json": json.dumps(
        {
            "mcpServers": {
                "hms-report": {
                    "command": "node",
                    "args": ["server.js"],
                    "env": {"HMS_PORTAL_PASSWORD": "${HMS_PORTAL_PASSWORD}"},
                }
            }
        }
    ),
    ".agents/mcps/hms-report/server.js": "console.log('hms')",
    ".agents/platform-docs/skills.md": "Base44's own docs",
    ".agents/leak.json": '{"api_key": "abcdef123456789"}',
    "base44/entities/TaskItem.jsonc": "{}",
    "base44/agents/your_agent.jsonc": '{"instructions": "Be helpful", "whatsapp_greeting": "hi"}',
    "base44/workflows/Weekly.jsonc": json.dumps(
        {
            "name": "Weekly",
            "description": "Weekly scout",
            "trigger": {
                "config": {
                    "trigger_type": "scheduled",
                    "cron_expression": "0 9 * * 0",
                    "timezone": "Asia/Jerusalem",
                }
            },
        }
    ),
    "base44/connectors/one_note.jsonc": '{"type": "one_note", "scopes": ["Notes.Read"]}',
    "notes/system-map/main.md": "# System map",
    "conversations/c1/plan.md": "The plan.",
}


def agent() -> Superagent:
    return Superagent(
        "a1",
        "business_dev",
        {
            "agents": {"your_agent": {"instructions": "Be helpful", "model": "automatic"}},
            "entities": {"TaskItem": {"type": "object"}},
        },
        {"slug": "koda"},
        dict(FILES),
        [{"id": "m1", "content": "Hours are reported weekly.", "scope": "user"}],
        ["c1"],
    )


class Reader:
    def __init__(self, messages):
        self.messages = messages
        self.problems = []

    def superagents(self):
        return [agent()]

    def conversation(self, agent, conversation_id):
        return {
            "id": "c1",
            "title": "Hours",
            "created_date": "2026-11-21T18:27:04",
            "summary": {"message_count": 500},
            "messages": self.messages,
        }


def message(n, role, text):
    return {"id": f"x{n}", "role": role, "content": text}


def test_a_superagent_is_saved_in_its_places_with_its_source(repo: ContentRepo):
    LocalHome().save_settings(content_repo=str(repo.root))
    reader = Reader([message(1, "user", "q1"), message(2, "assistant", "a1")])
    adapter = Base44Adapter(LocalHome(), reader_factory=lambda account: reader)
    adapter.install("base44-personal-cloud", "personal", repo.root, hooks=False)
    report = adapter.run_harvest()
    profile = "base44-personal-cloud"
    agent_file = repo.path("core", "agents", "business-dev.yaml").read_text()
    assert "I am Koda." in agent_file and f"profile: {profile}" in agent_file  # a source on every item
    assert "hms-time-report" in agent_file
    assert repo.path("core", "skills", "hms-time-report", "scripts", "run.sh").is_file()
    assert (
        "HMS_PORTAL_PASSWORD"
        in repo.path("core", "skills", "hms-time-report", "scripts", "engine.js").read_text()
    )
    assert repo.path("core", "plugins", "business-dev-mcp-hms-report", "server.js").is_file()
    rule = next(repo.path("core", "instructions").rglob("*delete-requires-approval.md")).read_text()
    assert "scope: agent:" in rule and "global" not in rule  # the agent's rule, not one for every tool
    app = repo.path("apps", "business-dev")
    assert (app / "entities.json").is_file() and (app / "entities" / "TaskItem.jsonc").is_file()
    # the app is the data model only; everything else is where it belongs, sourced from the profile
    assert sorted(p.name for p in app.iterdir()) == ["app.yaml", "entities", "entities.json"]
    plugin = repo.path("core", "plugins", "business-dev-mcp-hms-report")
    assert "<set in Base44>" in (plugin / "mcp-config.json").read_text()
    flow = repo.path("core", "workflows", "business-dev-weekly.yaml").read_text()
    assert (
        "0 9 * * 0 (Asia/Jerusalem)" in flow and "agent: business-dev" in flow and "profile: base44" in flow
    )
    assert "one-note" in repo.path("core", "connections.yaml").read_text()
    assert "whatsapp_greeting" in repo.path("core", "agents", "business-dev.yaml").read_text()
    everything = "".join(
        p.read_text(errors="ignore") for p in repo.root.rglob("*") if p.is_file() and ".git" not in p.parts
    )
    assert "hunter2" not in everything and "abcdef123456789" not in everything  # never a secret
    assert "Base44's own docs" not in everything
    assert any("looks like a secret" in e and "leak.json" in e for e in report.errors)
    log = repo.path("sessions", profile, "conversation-c1", "log.md").read_text()
    assert "q1" in log and "a1" in log
    reader.messages = [message(2, "assistant", "a1"), message(3, "user", "q2"), message(4, "assistant", "a2")]
    adapter.run_harvest()  # the API window moved on
    log = repo.path("sessions", profile, "conversation-c1", "log.md").read_text()
    assert log.index("q1") < log.index("q2")  # kept, and growing
    assert ProfileRegistry(repo).get(profile).tool == "base44"
    from conftest import validate

    report = validate(repo)
    assert report.ok, report.problems
