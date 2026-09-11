"""交付审核链：每个 done 的任务必须能回答「AI 自动还是真人审核」。

硬规则：reviewed_by 只能由真人路径（operator 干预 / human 节点）写入；
AI 执行路径显式打 ai_auto 且 reviewer 置空，杜绝 AI 自标「已人工审核」。
审核链随 delivery_fingerprint 入哈希——审核状态一变，旧验收即失效。
"""

from __future__ import annotations

from runtime.projectos.acceptance import delivery_fingerprint
from runtime.projectos.engine import ProjectEngine
from runtime.projectos.model import Milestone, Task
from runtime.projectos.store import ProjectStore


def _store_and_engine(tmp_path, decompose, **kwargs):
    store = ProjectStore(base_dir=tmp_path)
    engine = ProjectEngine(
        store,
        generate_milestones=lambda goal: [
            Milestone(id="M1", name="配图", goal=goal, success_criteria=["图合格"])
        ],
        decompose_tasks=decompose,
        qa_task=lambda task, ms: {"approved": True, "reason": "ok"},
        **kwargs,
    )
    return store, engine


def _decompose(mode):
    def build(ms):
        return [
            Task(
                id=f"{ms.id}-T1",
                milestone_id=ms.id,
                type="code",
                goal="产出 20 张配图",
                team_mode=mode,
            )
        ]

    return build


def _run(tmp_path, mode, **engine_kwargs):
    store, engine = _store_and_engine(tmp_path, _decompose(mode), **engine_kwargs)
    project = engine.plan("商品上新", "20 张配图")
    engine.run(project.id, max_ticks=5)
    return store, engine, project.id


def test_ai_delivery_is_stamped_ai_auto_with_no_reviewer(tmp_path):
    executed = []

    def executor(task, context):
        executed.append(task.id)
        return "AI 交付物"

    store, engine, project_id = _run(tmp_path, "single", execute_task=executor)
    task = store.tasks_for_milestone("M1")[0]

    assert executed == ["M1-T1"]
    assert task.status == "done"
    # An AI verdict can never be presented as a human approval.
    assert task.review_mode == "ai_auto"
    assert task.reviewed_by == ""


def test_operator_complete_signs_the_review_chain(tmp_path):
    store, engine, project_id = _run(tmp_path, "single", execute_task=lambda t, c: "草稿")
    engine.intervene_task(
        project_id, "M1-T1", action="complete", output="定稿", actor="op-42"
    )
    task = store.tasks_for_milestone("M1")[0]

    assert task.status == "done"
    assert task.review_mode == "operator"
    assert task.reviewed_by == "op-42"


def test_operator_skip_is_signed_too(tmp_path):
    store, engine, project_id = _run(tmp_path, "single", execute_task=lambda t, c: "草稿")
    engine.intervene_task(project_id, "M1-T1", action="skip", reason="不再需要", actor="op-7")
    task = store.tasks_for_milestone("M1")[0]

    assert task.status == "done"
    assert task.review_mode == "operator"
    assert task.reviewed_by == "op-7"


def test_operator_intervention_without_actor_falls_back_to_generic_label(tmp_path):
    store, engine, project_id = _run(tmp_path, "single", execute_task=lambda t, c: "草稿")
    engine.intervene_task(project_id, "M1-T1", action="complete", output="定稿")
    task = store.tasks_for_milestone("M1")[0]

    assert task.review_mode == "operator"
    assert task.reviewed_by == "operator"


def test_human_run_delivery_records_the_human_path(tmp_path):
    def human_runner(task, context):
        return {"completed_by": "u-9", "result": "真人交付：20 张照片"}

    store, engine, project_id = _run(tmp_path, "human", run_task_human=human_runner)
    task = store.tasks_for_milestone("M1")[0]

    assert task.status == "done"
    assert task.review_mode == "human_run"
    assert task.reviewed_by == "u-9"


def test_human_run_without_declared_identity_still_marks_the_mode(tmp_path):
    store, engine, project_id = _run(
        tmp_path, "human", run_task_human=lambda task, context: "真人交付物"
    )
    task = store.tasks_for_milestone("M1")[0]

    assert task.review_mode == "human_run"
    assert task.reviewed_by == "human"


def test_reset_clears_the_review_chain(tmp_path):
    store, engine, project_id = _run(tmp_path, "single", execute_task=lambda t, c: "草稿")
    engine.intervene_task(project_id, "M1-T1", action="complete", output="定稿", actor="op-42")
    engine.intervene_task(project_id, "M1-T1", action="reset")
    task = store.tasks_for_milestone("M1")[0]

    assert task.status == "pending"
    # A rerun invalidates any previous sign-off — no stale "reviewed by op-42".
    assert task.review_mode == ""
    assert task.reviewed_by == ""


def test_fingerprint_binds_the_review_chain():
    def build(reviewed_by):
        ms = Milestone(id="M1", name="m", goal="g", success_criteria=["ok"])
        task = Task(
            id="M1-T1", milestone_id="M1", type="code", goal="g",
            status="done", output="out", review_mode="operator", reviewed_by=reviewed_by,
        )
        return delivery_fingerprint(ms, [task])

    assert build("op-42") != build("op-7")
    assert build("op-42") == build("op-42")
