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
            "definition": {"do": "Call yemotBridgeWebhook"},
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
            "entities": {"TaskItem": {"type": "object"}, "Tenants": {"type": "object"}},
        },
        {"slug": "koda"},
        dict(FILES),
        [{"id": "m1", "content": "Hours are reported weekly.", "scope": "user"}],
        ["c1"],
        [
            {
                "name": "yemotBridgeWebhook",
                "entry": "main.ts",
                "automations": [],
                "files": [
                    {
                        "path": "main.ts",
                        "content": (
                            "const token = Deno.env.get('T'); TaskItem.create({});\n"
                            "async function f(token: string) {}"
                        ),
                    }
                ],
            },
            {
                "name": "leaky",
                "files": [{"path": "main.ts", "content": "const API_KEY = 'abcd1234efgh5678';"}],
            },
        ],
    )


def with_channels(a: Superagent) -> Superagent:
    a.channels = [
        {"channel": "whatsapp", "connected": True, "status": "connected"},
        {"channel": "telegram", "connected": False},
    ]
    a.settings_rows = {
        "ClientSetting": [
            {"id": "1", "key": "yemot_bridge_phone", "value": "0721234567", "created_date": "x"},
            {"id": "2", "key": "yemot_webhook_token", "value": "s3cr3t-value"},
        ]
    }
    a.goals = [
        {
            "name": "emergency-group-bridge",
            "title": "Emergency Group Bridge",
            "status": "active",
            "tasks": [{"id": "service-watch", "instruction": "Call yemotBridgeWebhook when needed"}],
        }
    ]
    a.webhooks = [
        {
            "target_url": "https://x.base44.app/functions/yemotBridgeWebhook",
            "events": ["message.created"],
            "description": "wake up",
        }
    ]
    return a


class Reader:
    def __init__(self, messages):
        self.messages = messages
        self.problems = []

    def superagents(self):
        return [with_channels(agent())]

    def conversation(self, agent, conversation_id, mentioned=False):
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
    assert sorted(p.name for p in app.iterdir()) == [
        "app.yaml",
        "data",
        "entities",
        "entities.json",
        "functions",
        "functions.json",
    ]
    assert (app / "functions" / "yemotBridgeWebhook" / "main.ts").is_file()  # code that names a token is fine
    leaky = (app / "functions" / "leaky" / "main.ts").read_text()  # the file is kept, its key is not
    assert "abcd1234efgh5678" not in leaky and "set it again" in leaky
    assert any("leaky" in h and "API_KEY" in h for h in report.hidden)  # and the owner is told which
    assert (app / "entities" / "Tenants.jsonc").is_file()  # a table only the app record has yet
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
    assert any("leak.json: api_key" in h for h in report.hidden)
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


def test_the_guide_and_the_connector_index_show_every_part_of_an_agent(repo: ContentRepo):
    from conftest import validate

    from harness.guide import RepoGuide
    from harness.inbox import HarnessIndex

    LocalHome().save_settings(content_repo=str(repo.root))
    reader = Reader([message(1, "user", "q1"), message(2, "assistant", "a1")])
    adapter = Base44Adapter(LocalHome(), reader_factory=lambda account: reader)
    adapter.install("base44-personal-cloud", "personal", repo.root, hooks=False)
    adapter.run_harvest()
    RepoGuide(repo).write()
    assert validate(repo).ok
    settings = repo.path("apps", "business-dev", "data", "ClientSetting.json").read_text()
    assert "yemot_bridge_phone" in settings and "072" in settings  # the settings code needs to run
    assert "s3cr3t-value" not in settings and "set it again" in settings  # a secret value is hidden
    goal = repo.path("core", "workflows", "business-dev-goal-emergency-group-bridge.yaml").read_text()
    assert "standing goal" in goal and "service-watch" in goal and "agent: business-dev" in goal
    connections = repo.path("core", "connections.yaml").read_text()
    assert "id: whatsapp" in connections and "telegram" not in connections  # connected channels only
    agent_file = repo.path("core", "agents", "business-dev.yaml").read_text()
    assert "whatsapp" in agent_file and "message.created" in agent_file  # channels and webhooks
    readme = repo.path("README.md").read_text()
    # the logic, with one real example of each kind - not a list of everything
    assert "## The logic of the structure" in readme and "connector/index.json" in readme
    assert (
        "`business-dev` (from `base44-personal-cloud`) is defined in `core/agents/business-dev.yaml`"
        in readme
    )
    assert (
        "a rule only it follows: `core/instructions/base44-personal-cloud/"
        "business-dev-delete-requires-approval.md`" in readme
    )
    assert "names the backend function `yemotBridgeWebhook`" in readme  # what calls what, found by name
    assert "table rows" in readme  # what stays in the tool, per tool
    before = len(readme)
    for n in range(30):  # more content does not make it longer
        repo.path("memory", f"extra-{n}.md").write_text("---\nsubject: more\n---\n\nMore.\n")
    RepoGuide(repo).write()
    assert abs(len(repo.path("README.md").read_text()) - before) < 200
    index = {e["path"]: e for e in HarnessIndex(repo).entries()}
    assert index["README.md"]["kind"] == "guide"
    function = index["apps/business-dev/functions/yemotBridgeWebhook/main.ts"]
    assert function["kind"] == "function" and function["agent"] == "business-dev"
    assert "core/workflows/business-dev-weekly.yaml" in function["used_by"]
    assert "core/workflows/business-dev-goal-emergency-group-bridge.yaml" in function["used_by"]
    assert index["core/workflows/business-dev-weekly.yaml"]["uses"] == ["function:yemotBridgeWebhook"]


def test_a_new_engine_rereads_everything_but_changes_only_what_differs(repo: ContentRepo, monkeypatch):
    import harness.harvest.item as item_module

    LocalHome().save_settings(content_repo=str(repo.root))
    reader = Reader([message(1, "user", "q1"), message(2, "assistant", "a1")])
    adapter = Base44Adapter(LocalHome(), reader_factory=lambda account: reader)
    adapter.install("base44-personal-cloud", "personal", repo.root, hooks=False)
    adapter.run_harvest()
    before = {p: p.read_text() for p in repo.path("core").rglob("*") if p.is_file()}
    monkeypatch.setattr(item_module, "__version__", "99.0.0")  # an engine upgrade
    report = adapter.run_harvest()
    after = {p: p.read_text() for p in repo.path("core").rglob("*") if p.is_file()}
    assert before == after  # re-read, nothing rewritten: no provenance entry for a non-change
    assert report.counts["unchanged"] and not report.counts["updated"]
