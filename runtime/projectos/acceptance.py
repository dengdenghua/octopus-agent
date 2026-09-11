"""Human acceptance is tied to the exact delivered task outputs."""

import hashlib
import json


def has_delivery_content(output):
    if output is None:
        return False
    if isinstance(output, str):
        return bool(output.strip())
    if isinstance(output, dict):
        return any(has_delivery_content(value) for value in output.values())
    if isinstance(output, (list, tuple)):
        return any(has_delivery_content(value) for value in output)
    return True


def delivery_fingerprint(milestone, tasks):
    payload = {
        "milestone_id": milestone.id,
        "name": milestone.name,
        "goal": milestone.goal,
        "approved_brief": milestone.spec.get("approved_brief"),
        "criteria": milestone.success_criteria,
        "tasks": [
            {"id": t.id, "status": t.status, "goal": t.goal,
             "criteria": t.acceptance_criteria, "output": t.output,
             "review_mode": t.review_mode, "reviewed_by": t.reviewed_by}
            for t in sorted(tasks, key=lambda t: t.id)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def delivery_accepted(store, project_id, milestone, tasks):
    if not tasks or any(t.status != "done" or not has_delivery_content(t.output) for t in tasks):
        return False
    fingerprint = delivery_fingerprint(milestone, tasks)
    return any(
        e.get("kind") == "project.delivery_accepted"
        and e.get("payload", {}).get("milestone_id") == milestone.id
        and e.get("payload", {}).get("fingerprint") == fingerprint
        for e in store.events_for_project(project_id, limit=1000)
    )
