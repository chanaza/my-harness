"""The monday probe against a fake API (introspection + counts)."""

from harness.adapters.monday import MondayProbe
from harness.credentials import CredentialStore


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
