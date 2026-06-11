import { beforeEach, describe, expect, test, vi } from "vitest";

import {
  assembleProjectTeam,
  bindProjectTeamRoom,
  createCompanyProject,
  createProjectBlueprint,
  createProjectMilestone,
  createProjectTask,
  createProjectTaskDependency,
  deleteCompanyProject,
  dispatchProjectTask,
  getProjectGantt,
  listCompanyProjects,
  listProjectArtifacts,
  listProjectInsights,
  materializeTeamAssemblyMember,
  updateProjectTask,
} from "./api";
import type { CompanyProject, GanttTaskView } from "./types";

const fetchMock = vi.fn();

function project(overrides: Partial<CompanyProject> = {}): CompanyProject {
  return {
    id: "proj-1",
    name: "Pilot Project",
    description: "",
    industry: "hardware",
    stage: "prototype",
    owner_id: null,
    team_room_id: null,
    ding_talk_group_id: null,
    start_date: null,
    target_end_date: null,
    status: "active",
    created_at: "2026-06-06T00:00:00Z",
    updated_at: "2026-06-06T00:00:00Z",
    metadata: {},
    ...overrides,
  };
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("company api", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  test("lists and creates company projects", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ projects: [project()], count: 1 }))
      .mockResolvedValueOnce(jsonResponse(project({ name: "New" })));

    await listCompanyProjects();
    await createCompanyProject({ name: "New" });

    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects",
      { headers: {} },
    ]);
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/company/projects",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: "",
          industry: "",
          stage: "idea",
          metadata: {},
          name: "New",
        }),
      },
    ]);
  });

  test("binds a company project to a team room", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        created: true,
        team_room_id: "team-1",
        team: { id: "team-1", name: "Project room" },
        project: project({ team_room_id: "team-1" }),
      }),
    );

    const result = await bindProjectTeamRoom("proj/1", {
      name: "Project room",
    });

    expect(result.project.team_room_id).toBe("team-1");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects/proj%2F1/team-room",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Project room" }),
      },
    ]);
  });

  test("creates a company project blueprint", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        project: project({ id: "proj-blueprint", name: "Blueprint" }),
        milestones: [],
        tasks: [],
        dependencies: [],
        blueprint: { budget_tier: "standard" },
      }),
    );

    const result = await createProjectBlueprint({
      prompt: "Launch a new company workflow",
    });

    expect(result.project.id).toBe("proj-blueprint");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects/blueprint",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          budget_tier: "standard",
          horizon_days: 90,
          metadata: {},
          prompt: "Launch a new company workflow",
        }),
      },
    ]);
  });

  test("deletes a company project", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        deleted: true,
        project_id: "proj-delete",
      }),
    );

    const result = await deleteCompanyProject("proj/delete");

    expect(result.deleted).toBe(true);
    expect(result.project_id).toBe("proj-delete");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects/proj%2Fdelete",
      {
        method: "DELETE",
        headers: {},
      },
    ]);
  });

  test("assembles a company project team", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        project: project({ id: "proj-assembly" }),
        members: [
          {
            id: "member-1",
            project_id: "proj-assembly",
            slot_id: "agent:planner",
            kind: "agent",
            role: "planner",
            display_name: "Planner Agent",
            status: "matched",
            source_agent_id: "general",
            source_agent_name: "General",
            match_score: 72,
          },
        ],
        budget_profile: { label: "standard" },
        summary: { total_slots: 1, matched_agents: 1 },
        available_agents_count: 3,
      }),
    );

    const result = await assembleProjectTeam("proj/assembly");

    expect(result.members[0].source_agent_id).toBe("general");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects/proj%2Fassembly/team-assembly",
      {
        method: "POST",
        headers: {},
      },
    ]);
  });

  test("materializes a team assembly member as an agent", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        project: project({ id: "proj/assembly" }),
        member: {
          id: "member-1",
          project_id: "proj/assembly",
          slot_id: "agent:planner",
          kind: "agent",
          role: "planner",
          display_name: "Planner Agent",
          status: "matched",
          source_agent_id: "company_planner",
          source_agent_name: "Company Planner",
        },
        agent: {
          id: "company_planner",
          name: "Company Planner",
          description: "Planner",
          agent_dir: "agents/company_planner",
          identity_card: {
            identity_number: "HA-ABC123",
          },
        },
        created: true,
        hot_loaded: true,
        requires_reload: false,
      }),
    );

    const result = await materializeTeamAssemblyMember(
      "proj/assembly",
      "member-1",
      { agent_id: "company_planner" },
    );

    expect(result.agent.id).toBe("company_planner");
    expect(result.agent.identity_card?.identity_number).toBe("HA-ABC123");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects/proj%2Fassembly/team-assembly/member-1/materialize",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id: "company_planner" }),
      },
    ]);
  });

  test("creates timeline entities and fetches gantt view", async () => {
    const gantt: GanttTaskView[] = [
      {
        id: "task-1",
        name: "PCB design",
        milestone_id: "mile-1",
        start: "2026-06-01",
        end: "2026-06-10",
        progress: 20,
        status: "doing",
        assignee: "ee",
        dependencies: ["task-0"],
        is_milestone: false,
        critical: false,
      },
    ];
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          id: "mile-1",
          project_id: "proj/1",
          title: "Hardware MVP",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "task-1",
          project_id: "proj/1",
          title: "PCB design",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "dep-1",
          project_id: "proj/1",
          from_task_id: "task-0",
          to_task_id: "task-1",
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ items: gantt, count: 1 }));

    await createProjectMilestone("proj/1", { title: "Hardware MVP" });
    await createProjectTask("proj/1", { title: "PCB design" });
    await createProjectTaskDependency("proj/1", {
      from_task_id: "task-0",
      to_task_id: "task-1",
    });
    const rows = await getProjectGantt("proj/1");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/company/projects/proj%2F1/milestones",
    );
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/company/projects/proj%2F1/tasks",
    );
    expect(fetchMock.mock.calls[2][0]).toBe(
      "/api/company/projects/proj%2F1/dependencies",
    );
    expect(fetchMock.mock.calls[3][0]).toBe(
      "/api/company/projects/proj%2F1/gantt",
    );
    expect(rows[0].dependencies).toEqual(["task-0"]);
  });

  test("updates project tasks and throws response details", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ id: "task-1", project_id: "proj-1", progress: 50 }),
      )
      .mockResolvedValueOnce(new Response("bad task", { status: 404 }));

    await updateProjectTask("task/1", { progress: 50 });
    await expect(updateProjectTask("missing", { progress: 10 })).rejects.toThrow(
      "Update project task failed: 404 bad task",
    );

    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/tasks/task%2F1",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ progress: 50 }),
      },
    ]);
  });

  test("lists project artifacts", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        artifacts: [
          {
            id: "task-1:report.md",
            project_id: "proj-1",
            task_id: "task-1",
            team_task_id: "team-task-1",
            source: "team_task",
            type: "markdown",
            title: "report.md",
            content: "# Report",
            path: "/tmp/report.md",
            url: null,
            created_at: "2026-06-07T00:00:00Z",
            metadata: { task_title: "Write report" },
          },
        ],
        count: 1,
      }),
    );

    const artifacts = await listProjectArtifacts("proj/1");

    expect(artifacts[0].title).toBe("report.md");
    expect(artifacts[0].metadata.task_title).toBe("Write report");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects/proj%2F1/artifacts",
      { headers: {} },
    ]);
  });

  test("lists project insights", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        insights: [
          {
            id: "task-1:artifact-1:risks:1",
            project_id: "proj-1",
            task_id: "task-1",
            team_task_id: "team-task-1",
            source_artifact_id: "task-1:artifact-1",
            kind: "risk",
            title: "Supply delay",
            detail: "Lead time is unknown.",
            severity: "high",
            owner: "ops",
            due_at: null,
            status: null,
            created_at: "2026-06-07T00:00:00Z",
            metadata: {},
          },
        ],
        count: 1,
        counts: { risk: 1, next_action: 0, decision: 0 },
      }),
    );

    const insights = await listProjectInsights("proj/1");

    expect(insights[0].kind).toBe("risk");
    expect(insights[0].severity).toBe("high");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/projects/proj%2F1/insights",
      { headers: {} },
    ]);
  });

  test("dispatches project tasks to team execution", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        created: true,
        run_requested: true,
        team_task_id: "team-task-1",
        team_task: { id: "team-task-1", room_id: "proj-1", title: "Run" },
        project_task: { id: "task-1", project_id: "proj-1", title: "Run" },
      }),
    );

    const result = await dispatchProjectTask("task/1", {
      room_id: "room-1",
      run: true,
    });

    expect(result.team_task_id).toBe("team-task-1");
    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/company/tasks/task%2F1/dispatch",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_id: "room-1", run: true }),
      },
    ]);
  });
});
