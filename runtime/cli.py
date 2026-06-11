# ruff: noqa: E402, I001 — module-level imports below intentionally appear after
# the dotenv bootstrap and configure_logging() call so that environment
# variables and logging are wired before any runtime module loads.
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from pathlib import Path


def _ensure_utf8_stdio() -> None:
    """Keep Windows packaged builds from crashing on non-ASCII status output."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


_ensure_utf8_stdio()

# Auto-load .env from cwd · quiet no-op if missing or python-dotenv absent.
# Must run BEFORE any module that reads env at import time (e.g. routers
# that probe ANTHROPIC_API_KEY in their constructor).
#
# Policy: .env values WIN over shell env. Two reasons:
#   1. Windows shells often pre-export empty placeholders
#      (``ANTHROPIC_API_KEY=``) that would otherwise block .env from
#      filling them in if we used ``override=False``.
#   2. ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL must stay paired · if a
#      shell exported the default base URL but .env configures a mirror
#      key, mixing them produces a silent 401. Letting .env fully win
#      keeps the paired credentials internally consistent.
# Operators who prefer shell-wins policy can simply not create .env.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(override=True)
    del _load_dotenv
except (ImportError, TypeError, AttributeError):  # noqa: BLE001 — dotenv optional; skip if module/env malformed
    pass

from runtime.platform.observability.logging_config import configure_logging

configure_logging()

_logger = logging.getLogger(__name__)

# Re-exports from sibling CLI modules (backward compatibility — tests
# and downstream callers import from ``runtime.cli``).
from runtime.cli_core import (  # noqa: F401
    _build_reflex_router,
    _build_stack,
    _Colors,
    _graph_has_template_deps,
    _make_router,
    _short_output,
    DEFAULT_RULES,
    print_cost_breakdown,
)
from runtime.cli_reflect import (
    run_intel,
    run_loop,
    run_optimize,
    run_reflect,
)
from runtime.cli_run import (
    run_bench,
    run_goal,
    run_goal_from_config,
    run_resume,
)
from runtime.cli_serve import (  # noqa: F401
    register_reflection_tasks as _register_reflection_tasks,
    run_serve,
)

from runtime.platform.i18n import _, set_lang

from . import __version__


def run_status(*, color: bool = True) -> int:
    from runtime.adapters.instrumentation import OTEL_AVAILABLE

    from . import __version__

    c = _Colors(color)

    def _check(label: str, import_path: str) -> tuple[str, str]:
        try:
            __import__(import_path)
            return "✓", "installed"
        except ImportError:
            return "✗", "not installed"

    def _line(ok: str, label: str, status: str) -> str:
        color_fn = c.green if ok == "✓" else c.dim
        return f"  {color_fn(ok)} {label:<28} · {status}"

    print(c.bold(_("cli.status.title_fmt", version=__version__)))
    print(c.dim("─" * 60))

    print(c.bold(_("cli.status.check_runtime")))
    ok, status = _check("pydantic", "pydantic")
    print(_line(ok, "pydantic (required)", status))
    print(_line(
        "✓" if OTEL_AVAILABLE else "✗",
        "opentelemetry",
        _("cli.status.otel_status", status=_("cli.status.otel_installed") if OTEL_AVAILABLE else _("cli.status.otel_missing")),
    ))

    print()
    print(c.bold(_("cli.status.check_llm")))
    print(_line("✓", "MockModelRouter", _("cli.status.mock_always_available")))
    ok, status = _check("anthropic", "anthropic")
    print(_line(ok, "AnthropicModelRouter", status))

    print()
    print(c.bold(_("cli.status.check_external")))
    ok, status = _check("httpx", "httpx")
    print(_line(ok, _("cli.status.httpx_web_skills"), status))
    ok, status = _check("mcp", "mcp")
    print(_line(ok, _("cli.status.mcp_stdio"), status))
    ok, status = _check("playwright", "playwright")
    print(_line(ok, _("cli.status.playwright_browser"), status))
    ok, status = _check("fastapi", "fastapi")
    print(_line(ok, _("cli.status.fastapi_web_ui"), status))

    from runtime.execution.suckers import SkillRegistry as _SR  # noqa: N814
    from runtime.execution.suckers.builtins import BUILTIN_NAMES, register_all

    reg = _SR()
    try:
        total = register_all(reg)
    except Exception as exc:
        print(c.red(_("cli.status.builtin_failed", error=exc)))
        return 1
    web_skills = [n for n in reg.all_names() if n not in BUILTIN_NAMES]

    print(c.bold(_("cli.status.check_builtin")))
    for name in BUILTIN_NAMES:
        desc = reg.get(name).description[:60]
        print(_("cli.status.skill_fmt", name=c.bold(name), desc=c.dim(desc)))
    if web_skills:
        print(c.bold(_("cli.status.check_web")))
        for name in web_skills:
            desc = reg.get(name).description[:60]
            print(_("cli.status.skill_fmt", name=c.bold(name), desc=c.dim(desc)))

    print(c.bold(_("cli.status.check_reflection")))
    reflection_items = [
        _("cli.status.reflection_list.skillforge"),
        _("cli.status.reflection_list.ruleextractor"),
        _("cli.status.reflection_list.kgupdater"),
        _("cli.status.reflection_list.memoryconsolidator"),
        _("cli.status.reflection_list.workflowrewriter"),
        _("cli.status.reflection_list.recipeevaluator"),
    ]
    for n, label in enumerate(reflection_items, 1):
        print(f"  {_('cli.status.reflection_fmt', n=n, label=label)}")

    print(c.bold(_("cli.status.check_cli")))
    cli_items = [
        ("demo", _("cli.status.cmd.demo")),
        ("run", _("cli.status.cmd.run")),
        ("bench", _("cli.status.cmd.bench")),
        ("intel", _("cli.status.cmd.intel")),
        ("kg", _("cli.status.cmd.kg")),
        ("reflect", _("cli.status.cmd.reflect")),
        ("status", _("cli.status.cmd.status")),
    ]
    for cmd, desc in cli_items:
        print(_("cli.status.cmd_fmt", cmd=c.bold(cmd), desc=c.dim(desc)))

    print(c.dim("\n" + "─" * 30))
    print(c.dim(_("cli.status.total_fmt", n=total)))
    return 0


def run_kg(
    *,
    from_journal: Path,
    subject: str | None = None,
    predicate: str | None = None,
    object_: str | None = None,
    neighbors: str | None = None,
    limit: int = 20,
    color: bool = True,
) -> int:
    from runtime.memory.journal import JSONLJournal
    from runtime.memory.knowledge_graph import KnowledgeGraph
    from runtime.safety.recovery import KGUpdater

    c = _Colors(color)
    if not from_journal.exists():
        print(c.red(_("cli.kg.not_found", path=from_journal)), file=sys.stderr)
        return 2

    journal = JSONLJournal(from_journal)
    kg = KnowledgeGraph()
    report = KGUpdater(journal=journal, kg=kg).update()

    print(c.bold(_("cli.kg.title_fmt", path=from_journal)))
    print(c.dim("─" * 60))
    print(
        _("cli.kg.scanned_fmt", scanned=report.events_scanned, accepted=report.triples_accepted, superseded=report.triples_superseded, ignored=report.triples_ignored)
    )
    print(c.dim(_("cli.kg.count_fmt", active=kg.count(), total=len(kg))))
    print()

    if neighbors is not None:
        triples = kg.neighbors(neighbors, hops=1)
        print(c.bold(_("cli.kg.neighbors_fmt", entity=repr(neighbors))))
    else:
        triples = kg.query(subject=subject, predicate=predicate, object=object_)
        filters = []
        if subject:
            filters.append(f"subject={subject!r}")
        if predicate:
            filters.append(f"predicate={predicate!r}")
        if object_:
            filters.append(f"object={object_!r}")
        descr = " · ".join(filters) if filters else _("cli.kg.filter_all")
        print(c.bold(_("cli.kg.matching_fmt", filters=descr, count=len(triples))))

    if not triples:
        print(c.dim(_("cli.kg.empty")))
        return 0

    print()
    for t in triples[:limit]:
        s = t.subject[:40]
        p = t.predicate[:20]
        o = t.object[:60]
        def _identity(x: str) -> str:
            return x
        conf_color = c.green if t.confidence >= 0.8 else (c.dim if t.confidence < 0.5 else _identity)
        print(f"  {conf_color(c.bold(s)):<40}  {c.cyan(p):<20}  {o}")
        print(c.dim(_("cli.kg.triple_detail_fmt", confidence=t.confidence, source=t.source.source_id)))
    if len(triples) > limit:
        print(c.dim(_("cli.kg.more_fmt", n=len(triples) - limit)))
    return 0


def run_backup(
    *,
    output: Path | None = None,
    base_dir: str = "~/.octopus",
    components: list[str] | None = None,
    color: bool = True,
) -> int:
    from runtime.platform.lifecycle.backup import BackupManager

    c = _Colors(color)
    mgr = BackupManager(base_dir=base_dir)
    report = mgr.backup(output=output, components=components)

    if not report.success:
        print(c.red(f"backup failed: {report.error}"), file=sys.stderr)
        return 1

    print(c.bold("backup created"))
    print(c.dim("─" * 60))
    print(f"  path:       {report.output_path}")
    print(f"  components: {', '.join(report.manifest.components)}")
    print(f"  files:      {report.manifest.total_files}")
    print(f"  size:       {report.manifest.total_bytes:,} bytes")
    print(f"  created:    {report.manifest.created_at}")
    return 0


def run_restore(
    *,
    input_path: Path,
    base_dir: str = "~/.octopus",
    components: list[str] | None = None,
    overwrite: bool = False,
    color: bool = True,
) -> int:
    from runtime.platform.lifecycle.backup import BackupManager

    c = _Colors(color)
    mgr = BackupManager(base_dir=base_dir)
    report = mgr.restore(input_path=input_path, components=components, overwrite=overwrite)

    if not report.success:
        print(c.red(f"restore failed: {report.error}"), file=sys.stderr)
        return 1

    print(c.bold("restore completed"))
    print(c.dim("─" * 60))
    print(f"  source:     {report.input_path}")
    print(f"  components: {', '.join(report.components_restored)}")
    print(f"  files:      {report.files_restored}")
    return 0


def run_export(
    *,
    output: Path,
    base_dir: str = "~/.octopus",
    components: list[str] | None = None,
    color: bool = True,
) -> int:
    from runtime.platform.lifecycle.backup import BackupManager

    c = _Colors(color)
    mgr = BackupManager(base_dir=base_dir)
    path = mgr.export_json(output=output, components=components)

    print(c.bold("export completed"))
    print(c.dim("─" * 60))
    print(f"  path: {path}")
    return 0


def run_wiki(
    *,
    from_journal: Path,
    output_dir: str = "~/.octopus/wiki",
    color: bool = True,
) -> int:
    from runtime.memory.journal import JSONLJournal
    from runtime.memory.diagnostics.wiki_compiler import WikiCompiler

    c = _Colors(color)

    if not from_journal.exists():
        print(c.red(f"journal not found: {from_journal}"), file=sys.stderr)
        return 2

    journal = JSONLJournal(from_journal)
    compiler = WikiCompiler(output_dir=output_dir)
    index = compiler.compile_from_journal(journal)

    print(c.bold("wiki compiled"))
    print(c.dim("─" * 60))
    print(f"  output_dir:    {output_dir}")
    print(f"  pages:         {index.total_pages}")
    print(f"  last_compiled: {index.last_compiled}")
    for page in index.pages:
        print(f"  - {page}")
    return 0

_CLI_COMMANDS = frozenset({
    "demo",
    "code",
    "mcp",
    "tour",
    "bugfix-demo",
    "bugfix-demo-v2",
    "reflection-demo",
    "evolution-demo",
    "run",
    "bench",
    "intel",
    "status",
    "quickstart",
    "reflect",
    "ui",
    "optimize",
    "resume",
    "serve",
    "loop",
    "kg",
    "backup",
    "restore",
    "export",
    "wiki",
    "setup",
    "doctor",
    "skills",
    "plugins",
})


def _normalize_cli_argv(argv: list[str]) -> list[str]:
    """Make the product-first path be a coding session.

    ``octopus-agent code ...`` remains explicit. If the user omits a
    subcommand, route the remaining arguments to ``code`` while preserving
    global flags such as ``--no-color`` and ``--lang``.
    """

    if not argv or any(token in {"-h", "--help", "--version"} for token in argv):
        return argv

    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token in _CLI_COMMANDS:
            return argv
        if token == "--no-color":
            idx += 1
            continue
        if token == "--lang":
            idx += 2
            continue
        if token.startswith("--lang="):
            idx += 1
            continue
        return [*argv[:idx], "code", *argv[idx:]]
    return argv


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``octopus-agent``.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ cli.py · navigation map (1357 lines).                              ║
    ║                                                                    ║
    ║   §1 _ensure_utf8_stdio                            ~L14            ║
    ║   §2 run_status (default subcommand)               ~L86            ║
    ║   §3 run_kg / run_backup / run_restore / run_export ~L184          ║
    ║   §4 run_wiki                                      ~L321           ║
    ║   §5 main (argparse dispatcher, ~720 lines)        ~L410           ║
    ║   §6 run_ui                                        ~L1134          ║
    ║   §7 run_setup / run_doctor / run_quickstart       ~L1165          ║
    ║   §8 run_skills                                    ~L1244          ║
    ║   §9 run_plugins                                   ~L1312          ║
    ╚════════════════════════════════════════════════════════════════════╝
    """
    argv = _normalize_cli_argv(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(
        prog="octopus-agent",
        description=_("Biomimetic self-evolving agent OS (MVP demo runner)."),
    )
    parser.add_argument("--version", action="version", version=f"octopus-agent {__version__}")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    parser.add_argument(
        "--lang", default="auto",
        choices=["auto", "en", "zh", "zh-CN", "ja", "ko"],
        help=_("cli.help.lang"),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help=_("cli.help.demo"))

    codep = sub.add_parser("code", help="Run an agentic coding session.")
    codep.add_argument("prompt", nargs="*", help="coding task prompt; omit to read stdin")
    codep.add_argument("--cwd", type=Path, default=None, help="workspace root (default: current directory)")
    codep.add_argument("--model", default=None, help="model name for the ReAct planner")
    codep.add_argument(
        "--permission-mode",
        choices=["default", "acceptEdits", "bypassPermissions", "plan"],
        default="default",
        help="approval policy for tool use",
    )
    codep.add_argument("--continue", dest="continue_session", action="store_true", help="resume latest coding session")
    codep.add_argument("--resume", default=None, help="resume a specific coding session id")
    codep.add_argument("--print", action="store_true", help="print only the final answer")
    codep.add_argument(
        "--output-format",
        choices=["text", "json", "stream-json"],
        default="text",
        help="output renderer",
    )
    codep.add_argument("--add-dir", action="append", default=[], help="additional readable workspace directory")
    codep.add_argument("--worktree", action="store_true", help="run with Octopus sandbox isolation metadata")
    codep.add_argument("--list-sessions", action="store_true", help="list saved coding sessions")
    codep.add_argument("--max-iterations", type=int, default=30)
    codep.add_argument("--max-tokens", type=int, default=50_000)
    codep.add_argument("--max-usd", type=float, default=0.50)
    codep.add_argument("--mock-response", default=None, help=argparse.SUPPRESS)

    mcpp = sub.add_parser("mcp", help="Manage MCP servers and trust.")
    mcp_sub = mcpp.add_subparsers(dest="mcp_op", required=True)
    mcp_add = mcp_sub.add_parser("add", help="Add an MCP stdio server.")
    mcp_add.add_argument("name", help="server name")
    mcp_add.add_argument("--env", action="append", default=[], help="environment variable KEY=VALUE")
    mcp_add.add_argument("--trust-level", default="custom", choices=["public", "custom", "external"])
    mcp_add.add_argument("--timeout-ms", type=int, default=30_000)
    mcp_add.add_argument("--disabled", action="store_true", help="save disabled")
    mcp_add.add_argument("--trust", action="store_true", help="also mark this server trusted")
    mcp_add.add_argument("server_command", nargs=argparse.REMAINDER, help="-- command args...")
    mcp_list = mcp_sub.add_parser("list", help="List MCP servers.")
    mcp_list.add_argument("--output-format", choices=["text", "json"], default="text")
    mcp_remove = mcp_sub.add_parser("remove", help="Remove an MCP server.")
    mcp_remove.add_argument("name", help="server name")
    mcp_remove.add_argument("--keep-trust", dest="forget_trust", action="store_false", help="keep trust entry")
    mcp_trust = mcp_sub.add_parser("trust", help="Trust an MCP server.")
    mcp_trust.add_argument("name", help="server name")
    mcp_trust.add_argument("--tool", dest="tools", action="append", default=[], help="pin an exposed tool name")
    mcp_trust.add_argument("--note", default="")
    mcp_revoke = mcp_sub.add_parser("revoke", help="Revoke MCP server trust.")
    mcp_revoke.add_argument("name", help="server name")

    mcp_serve = mcp_sub.add_parser("serve", help="Start Tentacle MCP Server (stdio or SSE mode).")
    mcp_serve.add_argument("--stdio", action="store_true", help="Run in stdio mode (for Claude Desktop command)")
    mcp_serve.add_argument("--host", default="0.0.0.0", help="Host for SSE mode (default: 0.0.0.0)")
    mcp_serve.add_argument("--port", type=int, default=8766, help="Port for SSE mode (default: 8766)")
    mcp_serve.add_argument("--log-level", default="warning", choices=["debug", "info", "warning", "error"], help="Log level")

    # tour · 5-minute interactive walkthrough
    tourp = sub.add_parser(
        "tour",
        help=_("cli.help.tour"),
    )
    tourp.add_argument(
        "--chapters", type=int, default=0,
        help="run only the first N chapters (0 = all)",
    )
    tourp.add_argument(
        "--no-pause", action="store_true",
        help="don't pause for Enter between chapters (for CI / screenshots)",
    )
    bugfixp = sub.add_parser(
        "bugfix-demo",
        help=_("cli.help.bugfix_demo"),
    )
    bugfixp.add_argument(
        "--workdir", type=Path, default=None,
        help="project root (default: tempdir)",
    )
    bugfixp.add_argument(
        "--no-color", action="store_true", default=argparse.SUPPRESS,
        help="disable ANSI colors",
    )

    bugfixp_v2 = sub.add_parser(
        "bugfix-demo-v2",
        help="Bug fix + MiniMax-style evolution loop · fix → update_soul → apply learned lesson on a different bug",
    )
    bugfixp_v2.add_argument(
        "--workdir", type=Path, default=None,
        help="project root (default: tempdir)",
    )
    bugfixp_v2.add_argument(
        "--no-color", action="store_true", default=argparse.SUPPRESS,
        help="disable ANSI colors",
    )

    reflectp_demo = sub.add_parser(
        "reflection-demo",
        help=_("cli.help.reflection_demo"),
    )
    reflectp_demo.add_argument("--workdir", type=Path, default=None)
    reflectp_demo.add_argument(
        "--runs", type=int, default=3,
        help="how many bugfix runs to populate the journal (default: 3)",
    )
    reflectp_demo.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)

    evolp_demo = sub.add_parser(
        "evolution-demo",
        help=_("cli.help.evolution_demo"),
    )
    evolp_demo.add_argument("--workdir", type=Path, default=None)
    evolp_demo.add_argument("--runs", type=int, default=3)
    evolp_demo.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)

    runp = sub.add_parser("run", help=_("cli.help.run"))
    runp.add_argument("goal", type=str, help="natural-language goal")
    runp.add_argument("--intent", default="task", help="intent type hint")
    runp.add_argument("--max-tokens", type=int, default=50_000)
    runp.add_argument("--max-usd", type=float, default=0.50)
    runp.add_argument(
        "--planner", choices=["static", "llm"], default="static",
        help="planning strategy (static=rule-based, llm=LLM-driven)",
    )
    runp.add_argument(
        "--model", default="mock/planner",
        help="LLM model (e.g. claude-haiku-4-5-20251001, or mock/X)",
    )
    runp.add_argument(
        "--mock-response", default=None,
        help="use MockModelRouter with this literal JSON response",
    )
    runp.add_argument(
        "--journal-file", type=Path, default=None,
        help="persist all events to a JSON Lines file (append-only)",
    )
    runp.add_argument(
        "--show-cost", action="store_true",
        help="print a per-step cost breakdown after execution",
    )
    runp.add_argument(
        "--swarm", action="store_true",
        help="dispatch TaskGraph nodes concurrently to multiple Arm workers",
    )
    runp.add_argument(
        "--max-workers", type=int, default=3,
        help="max concurrent arms when --swarm (default 3)",
    )
    runp.add_argument(
        "--learn-from", type=Path, default=None,
        help="JSONL journal file · preload LearnedRules into LLMPlanner before planning",
    )
    runp.add_argument(
        "--config", type=Path, default=None,
        help="YAML config file (overrides planner/budget/immunity/learn when set)",
    )

    # bench subcommand · real-sleep concurrency benchmark
    benchp = sub.add_parser(
        "bench", help=_("cli.help.bench")
    )
    benchp.add_argument("--tasks", type=int, default=4, help="number of parallel tasks")
    benchp.add_argument("--delay-ms", type=int, default=80, help="per-task sleep delay")
    benchp.add_argument("--workers", type=int, default=4, help="swarm max_workers")

    # intel subcommand · active learning · run IntelCollector once
    intelp = sub.add_parser(
        "intel", help=_("cli.help.intel")
    )
    intelp.add_argument("queries", nargs="+", help="one or more search queries")
    intelp.add_argument(
        "--fetch-top", type=int, default=0,
        help="for each query, fetch_url top N results (default 0)",
    )
    intelp.add_argument(
        "--max-results", type=int, default=5,
        help="per-query max search results (default 5)",
    )
    intelp.add_argument(
        "--journal-file", type=Path, default=None,
        help="persist intel events to JSONL (for --learn-from later)",
    )

    sub.add_parser(
        "status",
        help=_("cli.help.status"),
    )

    quickstartp = sub.add_parser(
        "quickstart",
        help="Bootstrap config, run doctor, and print the local start command.",
    )
    quickstartp.add_argument(
        "--output", "-o", type=Path, default=Path("config.yaml"),
        help="config path to create or reuse (default: ./config.yaml)",
    )
    quickstartp.add_argument(
        "--non-interactive", action="store_true",
        help="generate a minimal static config without prompts when config is missing",
    )
    quickstartp.add_argument(
        "--force", action="store_true",
        help="overwrite the config file instead of reusing it",
    )
    quickstartp.add_argument("--host", default="127.0.0.1")
    quickstartp.add_argument("--port", type=int, default=8000)
    quickstartp.add_argument(
        "--serve", action="store_true",
        help="start the FastAPI service after setup and doctor checks",
    )
    quickstartp.add_argument(
        "--learn-interval", type=int, default=0,
        help="periodic learn_from_journal interval in seconds when --serve is set",
    )

    reflectp = sub.add_parser(
        "reflect",
        help=_("cli.help.reflect"),
    )
    reflectp.add_argument("--from-journal", type=Path, required=True,
                          help="JSONL journal to analyze")
    reflectp.add_argument("--verbose", "-v", action="store_true",
                          help="print full details per producer")
    reflectp.add_argument("--skip", nargs="*", default=[],
                          choices=["skill_forge", "rule_extractor", "kg_updater",
                                   "memory", "workflow_rewriter", "recipe"],
                          help="skip specific producers")

    uip = sub.add_parser("ui", help=_("cli.help.ui"))
    uip.add_argument("--host", default="127.0.0.1")
    uip.add_argument("--port", type=int, default=8000)
    uip.add_argument(
        "--uds",
        type=str,
        default=None,
        metavar="PATH",
        help="Listen on a Unix domain socket instead of TCP.",
    )
    uip.add_argument("--journal", type=Path, default=None,
                     help="JSONL journal file to visualize (default: in-memory)")

    optp = sub.add_parser(
        "optimize",
        help=_("cli.help.optimize"),
    )
    optp.add_argument("goal", type=str, help="natural-language goal")
    optp.add_argument("--config", type=Path, required=True,
                      help="YAML config (LLM planner required)")
    optp.add_argument("--variants", type=Path, default=None,
                      help="initial variants YAML · omit to start with baseline")
    optp.add_argument("--journal", type=Path, required=True,
                      help="JSONL journal file · accumulates trajectories")
    optp.add_argument("--rounds", type=int, default=10,
                      help="evolution rounds (default 10)")
    optp.add_argument("--tasks-per-round", type=int, default=5,
                      help="tasks between each evolution step (default 5)")
    optp.add_argument("--mutator-model", type=str, default="mock/mutator",
                      help="LLM for PromptMutator (real: claude-haiku-4-5-20251001)")
    optp.add_argument("--mutator-response", type=str, default=None,
                      help="canned mutator response (for mock/* models)")
    optp.add_argument("--max-variants", type=int, default=8,
                      help="max pool size (default 8)")
    optp.add_argument("--retire-min-uses", type=int, default=5,
                      help="don't retire until ≥N uses (default 5)")
    optp.add_argument("--export", type=Path, default=None,
                      help="export winning variants to YAML")

    resumep = sub.add_parser(
        "resume",
        help=_("cli.help.resume"),
    )
    resumep.add_argument("--task-id", required=True,
                         help="original task UUID as seen in journal")
    resumep.add_argument("--journal", type=Path, required=True,
                         help="JSONL journal file with prior events")
    resumep.add_argument("--goal", type=str, required=True,
                         help="original natural-language goal (to re-plan graph)")
    resumep.add_argument("--config", type=Path, required=True,
                         help="YAML config · must match original planner setup")
    resumep.add_argument("--intent", default="task")
    resumep.add_argument("--dry-run", action="store_true",
                         help="print resume diagnostic · do not execute")

    servep = sub.add_parser(
        "serve",
        help=_("cli.help.serve"),
    )
    servep.add_argument("--config", type=Path, required=True,
                        help="YAML config (defines planner/journal/intel_sources)")
    servep.add_argument("--host", default="127.0.0.1")
    servep.add_argument("--port", type=int, default=8000)
    servep.add_argument(
        "--uds",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Listen on a Unix domain socket instead of TCP "
            "(e.g. /tmp/octopus.sock). "
            "When set, --host and --port are ignored. "
            "Electron / desktop clients connect via ws+unix:///PATH."
        ),
    )
    servep.add_argument("--learn-interval", type=int, default=0,
                        help="periodic learn_from_journal interval in seconds (0=off)")
    servep.add_argument("--prompt-variants", type=Path, default=None,
                        help="variants YAML · enables live A/B on /v1/chat/completions")
    servep.add_argument("--evolve-interval", type=int, default=0,
                        help="run evolver.step() every N seconds (0=off; needs --prompt-variants)")
    servep.add_argument("--mutator-model", type=str, default="mock/mutator",
                        help="LLM for PromptMutator (default mock · real: claude-haiku-4-5-20251001)")

    loopp = sub.add_parser(
        "loop",
        help=_("cli.help.loop"),
    )
    loopp.add_argument("goal", type=str, help="natural-language goal")
    loopp.add_argument("--config", type=Path, required=True,
                       help="YAML config (defines planner/budget/etc)")
    loopp.add_argument("--journal", type=Path, required=True,
                       help="JSONL journal file · reads for reflection, appends each iter")
    loopp.add_argument("--iterations", type=int, default=3,
                       help="number of run cycles (default 3)")
    loopp.add_argument("--intent", default="task")

    kgp = sub.add_parser(
        "kg", help="Build a KnowledgeGraph from a JSONL journal, then query."
    )
    kgp.add_argument("--from-journal", type=Path, required=True,
                     help="JSONL journal to load events from")

    backupp = sub.add_parser(
        "backup", help="Create a tar.gz backup of all Octopus data."
    )
    backupp.add_argument(
        "--output", "-o", type=Path, default=None,
        help="output tar.gz path (default: ~/.octopus/backup-<timestamp>.tar.gz)",
    )
    backupp.add_argument(
        "--base-dir", type=str, default="~/.octopus",
        help="Octopus data root (default: ~/.octopus)",
    )
    backupp.add_argument(
        "--components", nargs="*", default=None,
        choices=["journal", "kg", "config", "hot_cache", "skills", "agents"],
        help="components to include (default: all)",
    )

    restorep = sub.add_parser(
        "restore", help="Restore Octopus data from a tar.gz backup."
    )
    restorep.add_argument(
        "input", type=Path,
        help="backup tar.gz file to restore from",
    )
    restorep.add_argument(
        "--base-dir", type=str, default="~/.octopus",
        help="Octopus data root (default: ~/.octopus)",
    )
    restorep.add_argument(
        "--components", nargs="*", default=None,
        choices=["journal", "kg", "config", "hot_cache", "skills", "agents"],
        help="components to restore (default: all)",
    )
    restorep.add_argument(
        "--overwrite", action="store_true",
        help="overwrite existing files",
    )

    exportp = sub.add_parser(
        "export", help="Export Octopus data as human-readable JSON."
    )
    exportp.add_argument(
        "--output", "-o", type=Path, required=True,
        help="output JSON path",
    )
    exportp.add_argument(
        "--base-dir", type=str, default="~/.octopus",
        help="Octopus data root (default: ~/.octopus)",
    )
    exportp.add_argument(
        "--components", nargs="*", default=None,
        choices=["journal", "kg", "config", "hot_cache", "skills", "agents"],
        help="components to export (default: all)",
    )

    wikip = sub.add_parser(
        "wiki", help="Compile reflection outputs into a human-readable Markdown Wiki."
    )
    wikip.add_argument(
        "--from-journal", type=Path, required=True,
        help="JSONL journal to compile from",
    )
    wikip.add_argument(
        "--output-dir", type=str, default="~/.octopus/wiki",
        help="Wiki output directory (default: ~/.octopus/wiki)",
    )

    kgp.add_argument("--subject", default=None, help="filter by subject (exact match)")
    kgp.add_argument("--predicate", default=None, help="filter by predicate (exact match)")
    kgp.add_argument("--object", dest="object_", default=None, help="filter by object (exact match)")
    kgp.add_argument("--neighbors", default=None, help="print neighbors of this entity (1 hop)")
    kgp.add_argument("--limit", type=int, default=20, help="max triples to print")

    setupp = sub.add_parser(
        "setup", help="Interactive setup wizard · generate config.yaml in 3 minutes."
    )
    setupp.add_argument(
        "--output", "-o", type=Path, default=None,
        help="output config path (default: ./config.yaml)",
    )
    setupp.add_argument(
        "--non-interactive", action="store_true",
        help="generate minimal static config without prompts",
    )

    doctorp = sub.add_parser(
        "doctor", help="Check environment health · dependencies, API keys, config."
    )
    doctorp.add_argument(
        "--config", type=Path, default=None,
        help="config file to validate (optional)",
    )

    skillsp = sub.add_parser(
        "skills", help="Manage skills · list, search, install, publish."
    )
    skills_sub = skillsp.add_subparsers(dest="skills_op")
    skills_sub.add_parser("list", help="List installed skills.")
    skills_search = skills_sub.add_parser("search", help="Search skill marketplace.")
    skills_search.add_argument("query", help="search query")
    skills_search.add_argument("--limit", type=int, default=20)
    skills_install = skills_sub.add_parser("install", help="Install a skill from marketplace.")
    skills_install.add_argument("name", help="skill name to install")
    skills_uninstall = skills_sub.add_parser("uninstall", help="Uninstall a skill.")
    skills_uninstall.add_argument("name", help="skill name to uninstall")
    skills_info = skills_sub.add_parser("info", help="Show skill details.")
    skills_info.add_argument("name", help="skill name")
    skills_publish = skills_sub.add_parser("publish", help="Prepare a skill for publishing.")
    skills_publish.add_argument("path", type=Path, help="path to skill directory")

    pluginsp = sub.add_parser(
        "plugins", help="Manage plugins · list, discover, load."
    )
    plugins_sub = pluginsp.add_subparsers(dest="plugins_op")
    plugins_sub.add_parser("list", help="List loaded plugins.")
    plugins_sub.add_parser("discover", help="Discover available plugins.")
    plugins_load = plugins_sub.add_parser("load", help="Load a plugin by name.")
    plugins_load.add_argument("name", help="plugin name")

    args = parser.parse_args(argv)

    # Apply language setting
    if args.lang is not None:
        set_lang(args.lang)
    color = not args.no_color

    if args.command == "code":
        from runtime.cli_code import list_code_sessions, run_code_command
        if args.list_sessions:
            return list_code_sessions(args)
        return run_code_command(args, color=color)

    if args.command == "mcp":
        from runtime.cli_mcp import run_mcp_command
        return run_mcp_command(args)

    if args.command == "bugfix-demo":
        from demos.bugfix_demo import run_demo as _bugfix
        result = _bugfix(
            workdir=args.workdir,
            color=color and not args.no_color,
            verbose=True,
        )
        return 0 if result["success"] else 1

    if args.command == "bugfix-demo-v2":
        from demos.bugfix_demo_v2 import run_demo_v2 as _bugfix_v2
        result = _bugfix_v2(
            workdir=args.workdir,
            color=color and not args.no_color,
        )
        return 0 if result["success"] else 1

    if args.command == "reflection-demo":
        from demos.reflection_demo import run_demo as _reflect
        result = _reflect(
            workdir=args.workdir,
            runs=args.runs,
            color=color and not args.no_color,
            verbose=True,
        )
        return 0 if result["success"] else 1

    if args.command == "evolution-demo":
        from demos.evolution_demo import run_demo as _evolve
        result = _evolve(
            workdir=args.workdir,
            runs=args.runs,
            color=color and not args.no_color,
            verbose=True,
        )
        return 0 if result["success"] else 1

    if args.command == "demo":
        return run_goal(
            "list files in current dir and read README.md and count its words",
            intent_type="task",
            color=color,
            args_override={
                "intent_goal": "demo",
                "path": ".",
                "text": "demo-words-placeholder",
            },
        )

    if args.command == "run":
        if args.config is not None:
            return run_goal_from_config(
                goal=args.goal,
                config_path=args.config,
                intent_type=args.intent,
                color=color,
                show_cost=args.show_cost,
                swarm=args.swarm,
                max_workers=args.max_workers,
            )
        return run_goal(
            args.goal,
            intent_type=args.intent,
            max_tokens=args.max_tokens,
            max_usd=args.max_usd,
            color=color,
            planner_type=args.planner,
            planner_model=args.model,
            mock_response=args.mock_response,
            journal_file=args.journal_file,
            show_cost=args.show_cost,
            swarm=args.swarm,
            max_workers=args.max_workers,
            learn_from=args.learn_from,
        )

    if args.command == "bench":
        return run_bench(
            tasks=args.tasks,
            delay_ms=args.delay_ms,
            workers=args.workers,
            color=color,
        )

    if args.command == "intel":
        return run_intel(
            queries=args.queries,
            fetch_top=args.fetch_top,
            max_results=args.max_results,
            journal_file=args.journal_file,
            color=color,
        )

    if args.command == "kg":
        return run_kg(
            from_journal=args.from_journal,
            subject=args.subject,
            predicate=args.predicate,
            object_=args.object_,
            neighbors=args.neighbors,
            limit=args.limit,
            color=color,
        )

    if args.command == "backup":
        return run_backup(
            output=args.output,
            base_dir=args.base_dir,
            components=args.components,
            color=color,
        )

    if args.command == "restore":
        return run_restore(
            input_path=args.input,
            base_dir=args.base_dir,
            components=args.components,
            overwrite=args.overwrite,
            color=color,
        )

    if args.command == "export":
        return run_export(
            output=args.output,
            base_dir=args.base_dir,
            components=args.components,
            color=color,
        )

    if args.command == "wiki":
        return run_wiki(
            from_journal=args.from_journal,
            output_dir=args.output_dir,
            color=color,
        )

    if args.command == "reflect":
        return run_reflect(
            from_journal=args.from_journal,
            verbose=args.verbose,
            skip=set(args.skip),
            color=color,
        )

    if args.command == "status":
        return run_status(color=color)

    if args.command == "quickstart":
        return run_quickstart(
            output=args.output,
            non_interactive=args.non_interactive,
            force=args.force,
            host=args.host,
            port=args.port,
            serve=args.serve,
            learn_interval_s=args.learn_interval,
            color=color,
        )

    if args.command == "setup":
        return run_setup(
            output=args.output,
            non_interactive=args.non_interactive,
            color=color,
        )

    if args.command == "doctor":
        return run_doctor(
            config_path=args.config,
            color=color,
        )

    if args.command == "skills":
        return run_skills(args, color=color)

    if args.command == "plugins":
        return run_plugins(args, color=color)

    if args.command == "tour":
        from .tour import run_tour
        return run_tour(
            chapters=args.chapters or None,
            pause=not args.no_pause,
            color=color,
        )

    if args.command == "ui":
        return run_ui(
            host=args.host,
            port=args.port,
            uds=getattr(args, "uds", None),
            journal_path=args.journal,
        )

    if args.command == "loop":
        return run_loop(
            goal=args.goal,
            config_path=args.config,
            journal_path=args.journal,
            iterations=args.iterations,
            intent_type=args.intent,
            color=color,
        )

    if args.command == "serve":
        return run_serve(
            config_path=args.config,
            host=args.host,
            port=args.port,
            uds=getattr(args, "uds", None),
            learn_interval_s=args.learn_interval,
            prompt_variants_path=args.prompt_variants,
            evolve_interval_s=args.evolve_interval,
            mutator_model=args.mutator_model,
            color=color,
        )

    if args.command == "optimize":
        return run_optimize(
            goal=args.goal,
            config_path=args.config,
            variants_path=args.variants,
            journal_path=args.journal,
            rounds=args.rounds,
            tasks_per_round=args.tasks_per_round,
            mutator_model=args.mutator_model,
            mutator_response=args.mutator_response,
            max_variants=args.max_variants,
            retire_min_uses=args.retire_min_uses,
            export_path=args.export,
            color=color,
        )

    if args.command == "resume":
        return run_resume(
            task_id=args.task_id,
            journal_path=args.journal,
            goal=args.goal,
            config_path=args.config,
            intent_type=args.intent,
            dry_run=args.dry_run,
            color=color,
        )

    return 2


def run_ui(
    *,
    host: str,
    port: int,
    journal_path: Path | None,
    uds: str | None = None,
) -> int:
    try:
        import uvicorn
    except ImportError:
        print(_("cli.ui.not_installed"), file=sys.stderr)
        return 2
    try:
        from runtime.platform.ui import create_app
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2

    app = create_app(journal_path=journal_path)
    if uds:
        import os
        with contextlib.suppress(FileNotFoundError):
            os.unlink(uds)
        print(f"  unix socket: {uds}  (ws+unix:///{uds})")
        uvicorn.run(app, uds=uds, log_level="info")
    else:
        print(_("cli.ui.starting_fmt", host=host, port=port, journal=journal_path or "in-memory"))
        uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


def run_setup(
    *,
    output: Path | None = None,
    non_interactive: bool = False,
    color: bool = True,
) -> int:
    from runtime.platform.lifecycle.setup_wizard import SetupWizard

    wizard = SetupWizard(output_path=output, non_interactive=non_interactive)
    wizard.run()
    return 0


def run_doctor(
    *,
    config_path: Path | None = None,
    color: bool = True,
) -> int:
    from runtime.platform.observability.doctor import Doctor

    doctor = Doctor(config_path=config_path)
    report = doctor.run()
    print()
    print(report.summary())
    return 0 if report.all_ok else 1


def run_quickstart(
    *,
    output: Path,
    non_interactive: bool,
    force: bool,
    host: str,
    port: int,
    serve: bool,
    learn_interval_s: int,
    color: bool = True,
) -> int:
    c = _Colors(color)
    config_path = output

    print(c.bold("Octopus quickstart"))
    print(c.dim("─" * 60))

    if force or not config_path.exists():
        setup_rc = run_setup(
            output=config_path,
            non_interactive=non_interactive,
            color=color,
        )
        if setup_rc != 0:
            return setup_rc
    else:
        print(f"config: reusing {config_path}")

    print()
    print(c.bold("doctor"))
    doctor_rc = run_doctor(config_path=config_path, color=color)
    if doctor_rc != 0:
        print()
        print(c.red("quickstart stopped because doctor reported failures"))
        return doctor_rc

    print()
    print(c.green(f"ready: http://{host}:{port}"))
    if serve:
        return run_serve(
            config_path=config_path,
            host=host,
            port=port,
            learn_interval_s=learn_interval_s,
            color=color,
        )

    print(f"start: python -m runtime serve --config {config_path} --host {host} --port {port}")
    print("tip: add --serve to quickstart to start it immediately")
    return 0


def run_skills(args: argparse.Namespace, *, color: bool = True) -> int:
    from runtime.platform.plugins.skill_market import SkillMarket

    market = SkillMarket()
    op = getattr(args, "skills_op", None)

    if op == "list":
        installed = market.list_installed()
        if not installed:
            print("  No skills installed.")
            print("  Search: python -m runtime skills search <query>")
            return 0
        for s in installed:
            tags = f" [{', '.join(s.tags)}]" if s.tags else ""
            print(f"  · {s.name:<25s} v{s.version:<8s} {s.description[:40]}{tags}")
        return 0

    if op == "search":
        results = market.search(args.query, limit=args.limit)
        if not results:
            print(f"  No skills found for '{args.query}'.")
            return 0
        for r in results:
            status = "✓ installed" if r.installed else "  available"
            print(f"  · {r.name:<25s} {status:<14s} {r.description[:40]}")
        return 0

    if op == "install":
        result = market.install(args.name)
        icon = "✓" if result.status in ("installed", "updated") else "✗"
        print(f"  {icon} {result.message}")
        return 0 if result.status in ("installed", "updated", "already_installed") else 1

    if op == "uninstall":
        ok = market.uninstall(args.name)
        icon = "✓" if ok else "✗"
        print(f"  {icon} {'Uninstalled ' + args.name if ok else args.name + ' not found'}")
        return 0 if ok else 1

    if op == "info":
        info = market.info(args.name)
        if info is None:
            print(f"  Skill '{args.name}' not found.")
            return 1
        for k, v in info.items():
            if k == "skill_md":
                print(f"  {k}:")
                for line in str(v)[:500].split("\n"):
                    print(f"    {line}")
            elif isinstance(v, dict):
                print(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"  {k}: {v}")
        return 0

    if op == "publish":
        result = market.publish(args.path)
        status = result.get("status", "unknown")
        if status == "ready":
            print(f"  ✓ {result.get('message', '')}")
        else:
            print(f"  ✗ {result.get('message', 'Unknown error')}")
        return 0 if status == "ready" else 1

    print("  Usage: python -m runtime skills {list|search|install|uninstall|info|publish}")
    return 2


def run_plugins(args: argparse.Namespace, *, color: bool = True) -> int:
    from runtime.platform.plugins.plugin_loader import PluginLoader

    loader = PluginLoader()
    op = getattr(args, "plugins_op", None)

    if op == "list":
        plugins = loader.plugins
        if not plugins:
            print("  No plugins loaded.")
            print("  Discover: python -m runtime plugins discover")
            return 0
        for name, pi in plugins.items():
            state = pi.state.value
            hooks = ", ".join(pi.manifest.subscribes) if pi.manifest.subscribes else "none"
            print(f"  · {name:<25s} v{pi.manifest.version:<8s} [{state}] hooks=[{hooks}]")
        return 0

    if op == "discover":
        discovered = loader.discover()
        if not discovered:
            print("  No plugins found in ~/.octopus/plugins/")
            print("  Create a plugin: https://github.com/octopus-agent/octopus-agent/blob/main/docs/plugins.md")
            return 0
        print(f"  Found {len(discovered)} plugin(s):")
        for name in discovered:
            print(f"    · {name}")
        print("  Load: python -m runtime plugins load <name>")
        return 0

    if op == "load":
        pi = loader.load(args.name)
        if pi is None:
            print(f"  ✗ Plugin '{args.name}' not found.")
            return 1
        loader.start(args.name)
        hooks = ", ".join(pi.manifest.subscribes) if pi.manifest.subscribes else "none"
        print(f"  ✓ Loaded {pi.manifest.name} v{pi.manifest.version} · hooks=[{hooks}]")
        return 0

    print("  Usage: python -m runtime plugins {list|discover|load}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
