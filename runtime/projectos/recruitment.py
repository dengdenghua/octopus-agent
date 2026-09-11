"""Reviewable role provisioning requests; mutations stay in authorized APIs."""

import hashlib
import json
from pathlib import Path


def hub_candidates(goal):
    from runtime.platform.plugins.cloud_expert_store import CloudExpertStore

    store = CloudExpertStore(use_remote=False)
    catalog = json.loads(Path(__file__).with_name("role_catalog.json").read_text(encoding="utf-8"))
    allowed = {id for group in catalog["groups"] for id in group["ids"]}
    rows = [
        dict(row, display_name=catalog["names"][row["id"]])
        for row in store.list_experts(limit=500)["agents"]
        if row["id"] in allowed and not row.get("is_team")
    ]

    grams = {goal[i : i + 2].lower() for i in range(len(goal) - 1) if goal[i : i + 2].strip()}

    def score(row):
        text = (
            row.get("display_name", "")
            + row.get("profession", "")
            + " ".join(row.get("tags", []))
            + row.get("description", "")
        ).lower()
        return sum(gram in text for gram in grams)

    rows = sorted((r for r in rows if not r.get("is_team")), key=score, reverse=True)[:60]
    return [
        {
            "agent_id": "hub:" + row["id"],
            "name": row["display_name"],
            "description": row.get("description", "")[:600],
            "skills": ", ".join(row.get("tags", [])),
            "source": "hub",
        }
        for row in rows
    ]


def provisioning_requests(proposal, thread_id, hub):
    requests = []
    for need in proposal.staffing:
        if need.kind != "ai":
            continue
        if need.agent_id.startswith("hub:"):
            if need.agent_id not in hub:
                raise ValueError("unknown HUB role")
            requests.append(
                {
                    "source": "hub",
                    "key": need.agent_id,
                    "expert_id": need.agent_id[4:],
                    "name": hub[need.agent_id],
                }
            )
        elif need.source == "new":
            seed = f"{thread_id}:{need.role}:{need.responsibilities}"
            agent_id = "project_role_" + hashlib.sha256(seed.encode()).hexdigest()[:16]
            need.agent_id = agent_id
            soul = (
                f"你是{need.role}。\n职责：{need.responsibilities}\n交付物需提供依据并接受用户验收。"
                "\n权限遵循当前会话与工具审批；不得自行扩权、付款、聘用真人或冒充已完成操作。"
            )
            requests.append(
                {
                    "source": "new",
                    "key": agent_id,
                    "name": need.role,
                    "agent_id": agent_id,
                    "description": need.responsibilities,
                    "soul": soul,
                }
            )
    return list({item["key"]: item for item in requests}.values())
