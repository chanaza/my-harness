"""The monday probe (against a fake API) and the monday adapter (against a simulated reader)."""

import pytest
from conftest import validate

from harness import yaml_io
from harness.adapters.monday import MondayAdapter, MondayAgent, MondayProbe
from harness.credentials import CredentialStore
from harness.local import LocalHome
from harness.repo import ContentRepo
from harness.sessions import SessionRecord


class FakeMonday:
    api_version = "dev"

    def __init__(self):
        self.asked = []

    def query(self, text, variables=None):
        self.asked.append(text)
        if "me {" in text:
            return {"me": {"email": "me@example.com", "account": {"name": "Acme", "slug": "acme"}}}
        if "__schema" in text:
            def ref(name, is_list=False):
                named = {"kind": "OBJECT", "name": name}
                return {"kind": "LIST", "name": None, "ofType": named} if is_list else named
            return {"__schema": {"queryType": {"fields": [
                {"name": "agents", "args": [], "type": ref("Agent", True)},
                {"name": "agent_knowledge", "args": [{"name": "agent_id", "type": {"kind": "NON_NULL"}}],
                 "type": ref("AgentKnowledge")},
                {"name": "boards", "args": [], "type": ref("Board", True)},
            ]}}}
        if "__type" in text:
            fields = {"Agent": ["id", "name", "goal", "plan"], "AgentKnowledge": ["resources"]}
            return {"__type": {"fields": [{"name": f} for f in fields.get(variables["name"], [])]}}
        if "agents" in text:
            return {"agents": [{"id": "1"}, {"id": "2"}]}
        return {}


def test_probe_lists_agent_queries_and_counts():
    report = MondayProbe(FakeMonday()).run()
    text = "\n".join(report.lines())
    assert "agents -> Agent[]" in text and "agent_knowledge -> AgentKnowledge (needs: agent_id)" in text
    assert "Fields of Agent: id, name, goal, plan" in text
    assert report.counts["agents"] == "2"
    assert "boards" not in report.counts  # only what matters first


def test_tokens_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("HARNESS_MONDAY_DEFAULT_TOKEN", "secret")
    assert CredentialStore().get("monday:default") == "secret"


# --- the adapter, with a simulated reader shaped like a real account -----------------------



AGENT = {
    "id": "101", "kind": "PERSONAL", "state": "ACTIVE", "cursor": "changes-every-read", "is_running": False,
    "profile": {"name": "Sales Assistant", "role": "Sales", "role_description": "Prepares sales decks",
                "avatar_url": "https://x/a.png"},
    "goal": "Win deals", "identity": "Friendly and precise", "user_prompt": "Always answer in Hebrew.",
    "policies": [], "skill_ids": ["7"], "agent_model": None, "effective_agent_model": None,
    "mcp_tools": [{"kind": "MCP", "mcp_server": "gmail", "display_name": "Gmail", "description": "mail"}],
    "resources": [{"resource_id": "55", "scope_type": "BOARD"}], "knowledge": [],
}
JOB = {"job_id": "j1", "name": "Weekly summary", "instructions": "Summarise the board every Sunday.",
       "enabled": True, "triggers": [{"trigger_id": "t", "name": "Every week"}]}
RUN = {"run_id": "r1", "status": "COMPLETED", "title": "Prepare the Q1 deck",
       "started_at": "2026-11-10T09:00:00Z", "completed_at": "2026-11-10T09:05:00Z",
       "events": [{"event_type": "AGENT_MESSAGE", "data": "Done"}]}


class FakeReader:
    problems: list = []

    def agents(self):
        return [MondayAgent(AGENT, skills=["Board insights"],
                            knowledge={"resources": [{"resource_id": "55", "scope_type": "BOARD",
                                                      "permission_type": "READ"}], "files": []},
                            jobs=[JOB])]

    def workflows(self):
        return [{"id": "w1", "title": "New lead flow", "description": "Route new leads",
                 "workflow_blocks": [{"kind": "trigger"}]}]

    def runs(self, agent):
        return [RUN]


@pytest.fixture
def monday(repo: ContentRepo, tmp_path) -> MondayAdapter:
    LocalHome().save_settings(content_repo=str(repo.root))
    repo.config_file.update({"storage_by_profile.monday-work-cloud.transcripts.backend": "filesystem",
                             "storage_by_profile.monday-work-cloud.transcripts.path": str(tmp_path / "t")})
    adapter = MondayAdapter(LocalHome(), reader_factory=lambda account: FakeReader())
    adapter.install("monday-work-cloud", "work", hooks=False, account_key="acme")
    return adapter


def test_agents_jobs_workflows_and_runs_land_in_the_right_places(monday, repo: ContentRepo, tmp_path):
    report = monday.run_harvest()
    assert not report.errors, report.errors
    agent = yaml_io.load(repo.path("core", "agents", "sales-assistant.yaml").read_text())
    assert agent["instructions"] == "Always answer in Hebrew."
    assert agent["goal"] == "Win deals" and agent["role"] == "Sales"
    assert agent["skills"] == ["Board insights"]
    assert agent["knowledge"][0] == {"type": "BOARD", "id": "55", "permission": "READ"}
    assert agent["requires"] == {"connections": ["gmail"]}
    assert "cursor" not in agent["native"]["monday-work-cloud"]          # volatile fields dropped
    job = yaml_io.load(repo.path("core", "workflows", "sales-assistant-weekly-summary.yaml").read_text())
    assert job["steps"][0] == {"name": "run", "description": "Summarise the board every Sunday.",
                               "agent": "sales-assistant"}
    assert job["trigger"] == "Every week"
    assert repo.path("core", "workflows", "new-lead-flow.yaml").is_file()
    assert "gmail" in repo.path("core", "connections.yaml").read_text()
    meta = SessionRecord(repo, "monday-work-cloud", "run-r1").meta()
    assert meta["agent"] == "sales-assistant" and meta["topic"] == "Prepare the Q1 deck"
    assert (tmp_path / "t" / "monday-work-cloud" / "run-r1" / "run.json").is_file()
    assert validate(repo).ok, validate(repo).problems

    again = monday.run_harvest()
    assert not again.changed and not again.counts.get("conversations imported")   # nothing new


def test_agents_hidden_from_the_plain_listing_are_found_by_agent_user():
    """monday's plain agent listing can leave out some of the user's own agents (it did for
    one with many conversations); they are found through the account's agent users."""
    from harness.adapters.monday.reader import MondayReader

    class Client:
        def query(self, text):
            if "agents(limit: 100) { id }" in text:
                return {"agents": [{"id": "u1"}, {"id": "u2"}]}
            if "kinds: [PERSONAL]" in text:
                return {"custom_agents": [{"id": "1"}, {"id": "2"}]}
            if "kinds: [ACCOUNT_LEVEL]" in text:
                return {"custom_agents": []}
            if "custom_agents(limit: 100)" in text:
                return {"custom_agents": [{"id": "1"}]}
            return {}

    reader = MondayReader(Client())
    reader.schema.selection = lambda type_name: "id"
    reader._each = lambda *args: []
    assert sorted(agent.definition["id"] for agent in reader.agents()) == ["1", "2"]
