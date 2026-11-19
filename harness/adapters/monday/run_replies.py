"""A monday.com agent run as a ``Reply`` for the engine's log.

Only what is particular to monday lives here: the run's trigger (a chat message or a job),
its tool calls with their step summaries, and its answer (monday keeps the answer as the
run's response or summary, else as its last thinking event).
"""

from __future__ import annotations

from typing import Any

from ...conversation_log import Reply


def run_reply(run: dict[str, Any], number: int = 1) -> Reply:
    events = run.get("events") or (run.get("events_page") or {}).get("events") or []
    started = next((e.get("data") or {} for e in events if e.get("event_type") == "RUN_STARTED"), {})
    user = started.get("userMessage") or started.get("triggerName") or run.get("source") or ""
    summaries = {(e.get("data") or {}).get("stepId"): (e.get("data") or {}).get("summary")
                 for e in events if e.get("event_type") == "STEP_SUMMARY"}
    assistant: list[str] = []
    for event in events:
        data = event.get("data") or {}
        if event.get("event_type") == "TOOL_CALLED":
            what = summaries.get(data.get("toolCallId")) or _brief(data.get("toolInput"))
            assistant.append(Reply.action(str(data.get("toolName") or "tool"), what))
    answer = run.get("agent_response") or run.get("summary") or next(
        (str((e.get("data") or {}).get("content") or "") for e in reversed(events)
         if e.get("event_type") == "THINKING"), "")
    if answer:
        assistant.append(str(answer).strip())
    status = run.get("outcome_status") or run.get("status")
    if status and status not in ("success", "COMPLETED"):
        reason = f" - {run['outcome_reason']}" if run.get("outcome_reason") else ""
        assistant.append(f"*(run ended: {status}{reason})*")
    at = str(run.get("started_at") or "").split(".")[0].replace("T", " ")
    return Reply(number, f"{at} UTC" if at else "", [str(user)], assistant)


def _brief(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items() if not isinstance(v, (dict, list)))[:160]
    return str(value or "")[:160]
