---
type: "RuntimeSubsystem"
title: "All Skills 目录"
description: "全仓 Skill 目录 · 每个 skill 分 group / atomic 标记 · 决定哪个 arm 能包含它。"
tags: ["backend", "runtime"]
tier: "core"
---
# All Skills 目录

> 全仓 Skill 目录 · 每个 skill 分 group / atomic 标记 · 决定哪个 arm 能包含它。

**Source**: `runtime/execution/all_skills/`

## Package summary

runtime.execution.all_skills · unified skill catalog.

## Exports

- `ALL_SKILL_IDS`
- `BASE_SKILL_IDS`
- `skill_group`
- `skill_kind`
- `skills_in_group`
- `register_all`
- `register_base`
- `register_subset`
- `register_group`
- `WEB_ONLY_GROUPS`
- `is_known_but_disabled_tool`

## Modules

| Module | Summary |
| --- | --- |
| `agnes-image-generate/scripts/agnes_image_generate.py` | AI image generation skill — dual-provider (Volcano / Agnes). |
| `agnes-video-generate/scripts/agnes_video_generate.py` | AI video generation skill (async) — dual-provider (Volcano / Agnes). |
| `agnes-video-poll/scripts/agnes_video_poll.py` | Standalone skill entry for polling an Agnes video task. |
| `api-doc-gen/scripts/generate_api_doc.py` | Generate OpenAPI 3.0 spec from source code route definitions. |
| `auto-hypothesis-test/scripts/statistical_test_suite.py` | statistical_test_suite.py — 根据数据自动选择统计检验并输出通俗解读 |
| `auto-stat-test/scripts/statistical_test_suite.py` | statistical_test_suite.py — 根据数据自动选择统计检验并输出通俗解读 |
| `cn-finance-data/scripts/api_client.py` | Tushare API 客户端 |
| `code-mentor/scripts/analyze_code.py` | Code Analyzer - Static analysis tool for code review |
| `code-mentor/scripts/complexity_analyzer.py` | Complexity Analyzer - Analyze time and space complexity of algorithms |
| `code-mentor/scripts/run_tests.py` | Test Runner - Execute and format test results |
| `code-safety-audit/scripts/security_scan.py` | security_scan.py — 代码安全扫描工具 |
| `code-vuln-audit/scripts/security_scan.py` | security_scan.py — 代码安全扫描工具 |
| `data-viz-gen/scripts/build_infographic.py` | build_infographic.py — Generate self-contained HTML/SVG infographics from JSON data. |
| `data-viz-renderer/scripts/build_infographic.py` | build_infographic.py — Generate self-contained HTML/SVG infographics from JSON data. |
| `database-inspector/scripts/db_explorer.py` | db_explorer.py — SQLite / PostgreSQL 只读数据库探索工具 |
| `database-scout/scripts/db_explorer.py` | db_explorer.py — SQLite / PostgreSQL 只读数据库探索工具 |
| `email-to-calendar/scripts/tests/test_activity_ops.py` | Tests for utils/activity_ops.py |
| `email-to-calendar/scripts/tests/test_changelog_ops.py` | Tests for utils/changelog_ops.py |
| `email-to-calendar/scripts/tests/test_common.py` | Tests for utils/common.py |
| `email-to-calendar/scripts/tests/test_date_parser.py` | Tests for utils/date_parser.py |
| `email-to-calendar/scripts/tests/test_disposition_ops.py` | Tests for utils/disposition_ops.py |
| `email-to-calendar/scripts/tests/test_event_tracking.py` | Tests for utils/event_tracking.py |
| `email-to-calendar/scripts/tests/test_invite_ops.py` | Tests for utils/invite_ops.py |
| `email-to-calendar/scripts/tests/test_json_store.py` | Tests for utils/json_store.py |
| `email-to-calendar/scripts/tests/test_pending_ops.py` | Tests for utils/pending_ops.py |
| `email-to-calendar/scripts/tests/test_undo_ops.py` | Tests for utils/undo_ops.py |
| `email-to-calendar/scripts/utils/activity_ops.py` | Activity log operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/calendar_ops.py` | Provider-agnostic calendar operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/changelog_ops.py` | Changelog operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/common.py` | Shared utility functions for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/date_parser.py` | Shared date and time parsing utilities for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/disposition_ops.py` | Email disposition operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/email_ops.py` | Provider-agnostic email operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/event_tracking.py` | Event tracking operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/invite_ops.py` | Invite status operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/json_store.py` | Shared JSON file operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/pending_ops.py` | Pending invites operations for email-to-calendar skill. |
| `email-to-calendar/scripts/utils/undo_ops.py` | Undo operations for email-to-calendar skill. |
| `gantt-chart-builder/scripts/gantt_generator.py` | Project Timeline - 交互式 HTML 甘特图生成器 支持关键路径分析（CPM）、依赖关系可视化、浮动时间展示 |
| `general-writing/scripts/check_chapter_quality.py` | Chapter quality checker for fiction writing pipeline. Extends check_wordcount.py with em-dash density + English leakage scanning. Minimal, zero-dependency (stdlib only), sandbox-safe. |
| `general-writing/scripts/check_wordcount.py` | Word count checker for general-writing skills. Minimal, zero-dependency (stdlib only), sandbox-safe. |
| `gitlab-cli-guide/scripts/post-inline-comment.py` | post-inline-comment.py — Post inline diff comments on GitLab MRs via JSON body. |
| `gitlab-cli-skills/scripts/post-inline-comment.py` | post-inline-comment.py — Post inline diff comments on GitLab MRs via JSON body. |
| `http-load-profiler/scripts/http_benchmark.py` | HTTP 阶梯式并发压测工具 — 封装 ab/wrk + p50/p90/p99 + 拐点分析 |
| `http-load-tester/scripts/http_benchmark.py` | HTTP 阶梯式并发压测工具 — 封装 ab/wrk + p50/p90/p99 + 拐点分析 |
| `incident-retrospective/scripts/generate_postmortem.py` | Postmortem document generator. |
| `incident-review-guide/scripts/generate_postmortem.py` | Postmortem document generator. |
| `landing-page-scaffold/scripts/generate_landing_page.py` | Generate a self-contained landing page HTML wireframe. |
| `localization-toolkit/scripts/i18n_audit.py` | Audit i18n key usage vs locale JSON files. |
| `log-diagnostic/scripts/analyze_logs.py` | 日志分析工具：错误聚类 + 频率统计 + 时间分布，支持 JSON/syslog/Nginx 格式。 |
| `log-error-digest/scripts/analyze_logs.py` | 日志分析工具：错误聚类 + 频率统计 + 时间分布，支持 JSON/syslog/Nginx 格式。 |
| `pricing-advisor/scripts/pricing_modeler.py` | Pricing modeler — projects revenue at different price points and recommends tier structure. |
| `project-sizing-guide/scripts/estimate_calculator.py` | 软件项目工时估算计算器 支持三点估算 (PERT)、T-shirt Sizing、功能点分析 (FPA) |
| `py-perf-analyzer/scripts/perf_profile.py` | Python 性能分析工具 - cProfile + line_profiler + tracemalloc |
| `route-to-openapi/scripts/generate_api_doc.py` | Generate OpenAPI 3.0 spec from source code route definitions. |
| `seedance-video-generate/scripts/seedance_video_generate.py` | Seedance Video Generation Skill for Octopus-Agent Uses Volcano Engine Seedance API to generate videos from text, images, or existing videos. |
| `seedream-image-generate/scripts/seedream_image_generate.py` | Seedream Image Generation Skill for Octopus-Agent Uses Volcano Engine Seedream API to generate images from text prompts. |
| `sql-insight/scripts/sql_query_helper.py` | sql_query_helper.py — SQL 查询辅助工具：Schema 提取 / 查询优化分析 / EXPLAIN 解读 |
| `sql-tutor/scripts/sql_query_helper.py` | sql_query_helper.py — SQL 查询辅助工具：Schema 提取 / 查询优化分析 / EXPLAIN 解读 |
| `sun-path/scripts/annual_sun_hours.py` | Annual sun/shadow hours at a point. Given a building (footprint + height + rotation) and a point (x,y in meters from building center), compute total hours per year the point is in direct sun vs in building shadow vs night. Samples at configurable interval (default 1 hour) for memory efficiency on 1G |
| `sun-path/scripts/comfort_calc.py` | — |
| `sun-path/scripts/plot_sunpath.py` | — |
| `sun-path/scripts/shadow_calc.py` | — |
| `sun-path/scripts/sun_calc.py` | — |
| `sun-path/scripts/terrain_shadow.py` | Terrain shadow from DEM at a given time. Reads a GeoTIFF DEM, computes sun position, and outputs a binary shadow raster (1 = in shadow, 0 = in sun) and optional hillshade-style plot. Designed for modest memory use (process by blocks if needed); single read for small DEMs. |
| `sunlight-analysis/scripts/annual_sun_hours.py` | Annual sun/shadow hours at a point. Given a building (footprint + height + rotation) and a point (x,y in meters from building center), compute total hours per year the point is in direct sun vs in building shadow vs night. Samples at configurable interval (default 1 hour) for memory efficiency on 1G |
| `sunlight-analysis/scripts/comfort_calc.py` | — |
| `sunlight-analysis/scripts/plot_sunpath.py` | — |
| `sunlight-analysis/scripts/shadow_calc.py` | — |
| `sunlight-analysis/scripts/sun_calc.py` | — |
| `sunlight-analysis/scripts/terrain_shadow.py` | Terrain shadow from DEM at a given time. Reads a GeoTIFF DEM, computes sun position, and outputs a binary shadow raster (1 = in shadow, 0 = in sun) and optional hillshade-style plot. Designed for modest memory use (process by blocks if needed); single read for small DEMs. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `agnes-image-generate/scripts/agnes_image_generate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class AgnesConfig` | Runtime config resolved from env vars. |
| func | `def generate_image(prompt, model, size, n, image, api_key, base_url, extra)` | Generate one or more images via Volcano or Agnes. |

### `agnes-video-generate/scripts/agnes_video_generate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class AgnesConfig` |  |
| func | `def generate_video(prompt, model, width, height, num_frames, frame_rate, image, seed, wait, max_wait_seconds, poll_interval_seconds, api_key, base_url, extra)` | Create a video generation task and (optionally) wait for completion. |
| func | `def poll_video(task_id, api_key, base_url)` | One-shot status poll for a previously-submitted task. |

### `agnes-video-poll/scripts/agnes_video_poll.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def poll_agnes_video(task_id, api_key, base_url)` | One-shot status poll for an Agnes video generation task. |

### `api-doc-gen/scripts/generate_api_doc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def convert_path_params(path, framework)` | Convert framework path-param syntax to OpenAPI {param} format. |
| func | `def extract_docstring(node)` | Extract docstring from a Python function AST node. |
| func | `def annotation_to_str(node)` | Convert an AST annotation node to its string representation. |
| func | `def python_type_to_schema(type_str)` | Map a Python type-annotation string to an OpenAPI schema dict. |
| class | `class PythonExtractor` | Extract API routes from Python source files via AST. |
| class | `class JSExtractor` | Extract API routes from JS/TS files (Express.js). |
| class | `class GoExtractor` | Extract API routes from Go files (Gin, Echo). |
| func | `def build_openapi_spec(routes, title, version, description, servers)` |  |
| func | `def detect_framework(source_dir)` |  |
| func | `def scan_and_extract(source_dir, framework)` |  |
| func | `def to_yaml(obj, indent)` | Minimal YAML serializer sufficient for OpenAPI specs. |
| func | `def main()` |  |

### `auto-hypothesis-test/scripts/statistical_test_suite.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def load_data(path)` |  |
| func | `def is_categorical(series, max_unique_abs, max_unique_ratio)` |  |
| func | `def check_normality(data, alpha)` |  |
| func | `def check_equal_variance(groups, alpha)` |  |
| func | `def round_p(p)` |  |
| func | `def format_p_text(p)` |  |
| func | `def significance_label(p)` |  |
| func | `def run_independent_ttest(groups, group_names, alpha)` |  |
| func | `def run_mann_whitney(groups, group_names)` |  |
| func | `def run_one_way_anova(groups, group_names)` |  |
| func | `def run_kruskal_wallis(groups, group_names)` |  |
| func | `def run_chi_square(df, col1, col2)` |  |
| func | `def run_paired_ttest(d1, d2, name1, name2)` |  |
| func | `def run_wilcoxon(d1, d2, name1, name2)` |  |
| func | `def interpret(result, alpha)` |  |
| func | `def auto_select_and_run(df, group_col, value_col, col1, col2, paired, force_test, alpha)` |  |
| func | `def main()` |  |

### `auto-stat-test/scripts/statistical_test_suite.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def load_data(path)` |  |
| func | `def is_categorical(series, max_unique_abs, max_unique_ratio)` |  |
| func | `def check_normality(data, alpha)` |  |
| func | `def check_equal_variance(groups, alpha)` |  |
| func | `def round_p(p)` |  |
| func | `def format_p_text(p)` |  |
| func | `def significance_label(p)` |  |
| func | `def run_independent_ttest(groups, group_names, alpha)` |  |
| func | `def run_mann_whitney(groups, group_names)` |  |
| func | `def run_one_way_anova(groups, group_names)` |  |
| func | `def run_kruskal_wallis(groups, group_names)` |  |
| func | `def run_chi_square(df, col1, col2)` |  |
| func | `def run_paired_ttest(d1, d2, name1, name2)` |  |
| func | `def run_wilcoxon(d1, d2, name1, name2)` |  |
| func | `def interpret(result, alpha)` |  |
| func | `def auto_select_and_run(df, group_col, value_col, col1, col2, paired, force_test, alpha)` |  |
| func | `def main()` |  |

### `cn-finance-data/scripts/api_client.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TushareAPI` | Tushare API 客户端 |

### `code-mentor/scripts/analyze_code.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CodeIssue` | Represents a code issue found during analysis. |
| class | `class PythonAnalyzer` | Analyzer for Python code. |
| class | `class JavaScriptAnalyzer` | Basic analyzer for JavaScript code. |
| class | `class CodeMetrics` | Calculate code metrics. |
| func | `def detect_language(filename)` | Detect programming language from file extension. |
| func | `def analyze_file(filepath, output_format)` | Analyze a code file. |
| func | `def main()` |  |

### `code-mentor/scripts/complexity_analyzer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ComplexityAnalyzer(ast.NodeVisitor)` | Analyze time and space complexity of Python code. |
| func | `def format_output(results, output_format)` | Format analysis results. |
| func | `def analyze_file(filepath, function_name, output_format)` | Analyze a Python file. |
| func | `def analyze_code_snippet(code, output_format)` | Analyze a code snippet. |
| func | `def main()` |  |

### `code-mentor/scripts/run_tests.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestResult` | Represents test execution results. |
| class | `class TestRunner` | Base class for test runners. |
| class | `class PytestRunner(TestRunner)` | Run pytest tests. |
| class | `class UnittestRunner(TestRunner)` | Run unittest tests. |
| class | `class JestRunner(TestRunner)` | Run Jest tests. |
| func | `def detect_framework(target)` | Detect testing framework to use. |
| func | `def run_tests(target, framework, output_format)` | Run tests and format output. |
| func | `def main()` |  |

### `code-safety-audit/scripts/security_scan.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def shannon_entropy(data)` | Calculate Shannon entropy of a string. |
| class | `class Finding` |  |
| func | `def walk_files(root, exclude_dirs, max_file_kb)` | Yield (path, relative_path) for scannable text files. |
| func | `def read_lines(fpath)` | Read file lines, returning empty list for binary/undecodable files. |
| func | `def scan_npm(project_dir)` | Run npm audit and return findings. |
| func | `def scan_pip(project_dir)` | Run pip-audit and return findings. |
| func | `def scan_secrets(root, exclude_dirs, max_file_kb)` | Scan for hardcoded secrets using regex + entropy. |
| func | `def scan_owasp(root, exclude_dirs, max_file_kb)` | Scan for OWASP security anti-patterns. |
| func | `def format_text(target, modules, findings)` | Format findings as human-readable text. |
| func | `def format_json(target, modules, findings)` | Format findings as JSON. |
| func | `def deduplicate(findings)` | Remove duplicate findings (same file + line + name). |
| func | `def build_parser()` |  |
| func | `def main()` |  |

### `code-vuln-audit/scripts/security_scan.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def shannon_entropy(data)` | Calculate Shannon entropy of a string. |
| class | `class Finding` |  |
| func | `def walk_files(root, exclude_dirs, max_file_kb)` | Yield (path, relative_path) for scannable text files. |
| func | `def read_lines(fpath)` | Read file lines, returning empty list for binary/undecodable files. |
| func | `def scan_npm(project_dir)` | Run npm audit and return findings. |
| func | `def scan_pip(project_dir)` | Run pip-audit and return findings. |
| func | `def scan_secrets(root, exclude_dirs, max_file_kb)` | Scan for hardcoded secrets using regex + entropy. |
| func | `def scan_owasp(root, exclude_dirs, max_file_kb)` | Scan for OWASP security anti-patterns. |
| func | `def format_text(target, modules, findings)` | Format findings as human-readable text. |
| func | `def format_json(target, modules, findings)` | Format findings as JSON. |
| func | `def deduplicate(findings)` | Remove duplicate findings (same file + line + name). |
| func | `def build_parser()` |  |
| func | `def main()` |  |

### `data-viz-gen/scripts/build_infographic.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def main()` |  |

### `data-viz-renderer/scripts/build_infographic.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def main()` |  |

### `database-inspector/scripts/db_explorer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SQLiteExplorer` |  |
| class | `class PostgreSQLExplorer` |  |
| func | `def build_parser()` |  |
| func | `def main()` |  |

### `database-scout/scripts/db_explorer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SQLiteExplorer` |  |
| class | `class PostgreSQLExplorer` |  |
| func | `def build_parser()` |  |
| func | `def main()` |  |

### `email-to-calendar/scripts/tests/test_activity_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestStartSession(unittest.TestCase)` | Tests for start_session function. |
| class | `class TestLogSkip(unittest.TestCase)` | Tests for log_skip function. |
| class | `class TestLogEvent(unittest.TestCase)` | Tests for log_event function. |
| class | `class TestEndSession(unittest.TestCase)` | Tests for end_session function. |
| class | `class TestShowActivity(unittest.TestCase)` | Tests for show_activity function. |

### `email-to-calendar/scripts/tests/test_changelog_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestLogCreate(unittest.TestCase)` | Tests for log_create function. |
| class | `class TestLogUpdate(unittest.TestCase)` | Tests for log_update function. |
| class | `class TestLogDelete(unittest.TestCase)` | Tests for log_delete function. |
| class | `class TestListChanges(unittest.TestCase)` | Tests for list_changes function. |
| class | `class TestCanUndo(unittest.TestCase)` | Tests for can_undo function. |
| class | `class TestGetChange(unittest.TestCase)` | Tests for get_change function. |
| class | `class TestMaxChangesLimit(unittest.TestCase)` | Tests for MAX_CHANGES limit enforcement. |

### `email-to-calendar/scripts/tests/test_common.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestGetDayOfWeek(unittest.TestCase)` | Tests for get_day_of_week function. |
| class | `class TestFormatTimestamp(unittest.TestCase)` | Tests for format_timestamp function. |
| class | `class TestGenerateId(unittest.TestCase)` | Tests for generate_id function. |
| class | `class TestGenerateIndexedId(unittest.TestCase)` | Tests for generate_indexed_id function. |
| class | `class TestTimeAgo(unittest.TestCase)` | Tests for time_ago function. |

### `email-to-calendar/scripts/tests/test_date_parser.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestParseDate(unittest.TestCase)` | Tests for parse_date function. |
| class | `class TestParseTime(unittest.TestCase)` | Tests for parse_time function. |

### `email-to-calendar/scripts/tests/test_disposition_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestGetDispositionSettings(unittest.TestCase)` | Tests for get_disposition_settings function. |
| class | `class TestDispositionEmail(unittest.TestCase)` | Tests for disposition_email function. |
| class | `class TestIsCalendarReply(unittest.TestCase)` | Tests for is_calendar_reply function. |

### `email-to-calendar/scripts/tests/test_event_tracking.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestTrackEvent(unittest.TestCase)` | Tests for track_event function. |
| class | `class TestUpdateTrackedEvent(unittest.TestCase)` | Tests for update_tracked_event function. |
| class | `class TestDeleteTrackedEvent(unittest.TestCase)` | Tests for delete_tracked_event function. |
| class | `class TestLookupEvents(unittest.TestCase)` | Tests for lookup_events function. |

### `email-to-calendar/scripts/tests/test_invite_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestUpdateInviteStatus(unittest.TestCase)` | Tests for update_invite_status function. |

### `email-to-calendar/scripts/tests/test_json_store.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestEnsureDir(unittest.TestCase)` | Tests for ensure_dir function. |
| class | `class TestLoadJson(unittest.TestCase)` | Tests for load_json function. |
| class | `class TestSaveJson(unittest.TestCase)` | Tests for save_json function. |

### `email-to-calendar/scripts/tests/test_pending_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestListPendingJson(unittest.TestCase)` | Tests for list_pending_json function. |
| class | `class TestListPendingSummary(unittest.TestCase)` | Tests for list_pending_summary function. |
| class | `class TestAutoDismiss(unittest.TestCase)` | Tests for auto-dismiss functionality. |
| class | `class TestUpdateReminded(unittest.TestCase)` | Tests for update-reminded functionality. |
| class | `class TestAddPendingInvite(unittest.TestCase)` | Tests for add_pending_invite function. |

### `email-to-calendar/scripts/tests/test_undo_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TestFindLastUndoable(unittest.TestCase)` | Tests for find_last_undoable function. |
| class | `class TestListUndoable(unittest.TestCase)` | Tests for list_undoable function. |
| class | `class TestMarkUndone(unittest.TestCase)` | Tests for mark_undone function. |

### `email-to-calendar/scripts/utils/activity_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def start_session()` | Start a new processing session. |
| func | `def log_skip(email_id, subject, reason)` | Log a skipped email. |
| func | `def log_event(email_id, title, action, reason)` | Log an extracted event. |
| func | `def end_session()` | Finalize the current session and append to activity log. |
| func | `def show_activity(last_n)` | Show recent activity sessions. |
| func | `def main()` |  |

### `email-to-calendar/scripts/utils/calendar_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_provider(provider)` | Get the provider to use, from parameter or config. |
| func | `def get_calendar_id()` | Get the default calendar ID from config. |
| func | `def search_events(calendar_id, from_dt, to_dt, provider)` | Search for calendar events in a date range. |
| func | `def create_event(summary, from_dt, to_dt, description, attendees, calendar_id, reminders, rrule, provider)` | Create a new calendar event. |
| func | `def update_event(event_id, summary, from_dt, to_dt, description, add_attendees, calendar_id, provider)` | Update an existing calendar event. |
| func | `def delete_event(event_id, calendar_id, provider)` | Delete a calendar event. |
| func | `def main()` | CLI interface for calendar operations. |

### `email-to-calendar/scripts/utils/changelog_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def log_create(event_id, calendar_id, summary, start_time, end_time, email_id)` | Log a create action. Returns the change ID. |
| func | `def log_update(event_id, calendar_id, before_json, after_json, email_id)` | Log an update action. Returns the change ID. |
| func | `def log_delete(event_id, calendar_id, before_json)` | Log a delete action. Returns the change ID. |
| func | `def list_changes(last_n)` | Print recent changes to stdout. |
| func | `def get_change(change_id)` | Print a specific change as JSON. |
| func | `def can_undo(change_id)` | Check if a change can be undone. Prints 'true' or 'false'. |
| func | `def main()` |  |

### `email-to-calendar/scripts/utils/common.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_day_of_week(date_str)` | Get day of week name from a date string. |
| func | `def format_timestamp(iso_str, fmt)` | Format an ISO timestamp string to a human-readable format. |
| func | `def generate_id(prefix)` | Generate a unique ID with timestamp and counter placeholder. |
| func | `def generate_indexed_id(prefix, index)` | Generate a unique ID with timestamp and index. |
| func | `def time_ago(iso_timestamp)` | Get a human-readable 'time ago' string. |

### `email-to-calendar/scripts/utils/date_parser.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def parse_date(date_str)` | Parse various date formats to ISO format (YYYY-MM-DD). |
| func | `def parse_time(time_str)` | Parse various time formats to HH:MM format. |
| func | `def main()` |  |

### `email-to-calendar/scripts/utils/disposition_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_disposition_settings(config_file)` | Get email disposition settings from config. |
| func | `def disposition_email(email_id, settings, mark_read, archive, provider)` | Apply disposition (mark read/archive) to an email based on config. |
| func | `def is_calendar_reply(subject)` | Check if an email subject indicates it's a calendar reply. |
| func | `def main()` | CLI interface for disposition operations. |

### `email-to-calendar/scripts/utils/email_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_provider(provider)` | Get the provider to use, from parameter or config. |
| func | `def get_gmail_account()` | Get the Gmail account from config. |
| func | `def read_email(email_id, provider)` | Read a single email by ID. |
| func | `def search_emails(query, max_results, include_body, provider)` | Search for emails matching a query. |
| func | `def modify_email(email_id, remove_labels, add_labels, provider)` | Modify an email (add/remove labels). |
| func | `def send_email(to, subject, body, provider)` | Send an email. |
| func | `def main()` | CLI interface for email operations. |

### `email-to-calendar/scripts/utils/event_tracking.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def track_event(event_id, calendar_id, email_id, summary, start)` | Track a new or updated event. |
| func | `def update_tracked_event(event_id, summary, start)` | Update a tracked event's metadata. |
| func | `def delete_tracked_event(event_id)` | Delete an event from tracking. |
| func | `def lookup_events(search_type, search_value, validate, script_dir, provider)` | Look up tracked events and print as JSON. |
| func | `def main()` |  |

### `email-to-calendar/scripts/utils/invite_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def update_invite_status(invite_id, email_id, event_title, new_status, calendar_event_id)` | Update the status of a pending invite event. |
| func | `def main()` |  |

### `email-to-calendar/scripts/utils/json_store.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def ensure_dir(filepath)` | Ensure the directory for a file path exists. |
| func | `def load_json(filepath, default)` | Load JSON from a file. |
| func | `def save_json(filepath, data, indent)` | Save data as JSON to a file. |

### `email-to-calendar/scripts/utils/pending_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def add_pending_invite(email_id, email_subject, events)` | Add or update a pending invite with events. |
| func | `def list_pending_summary(today, update_reminded, auto_dismiss)` | Print human-readable summary of pending invites. |
| func | `def list_pending_json(today, update_reminded, auto_dismiss)` | Print JSON array of pending invites. |
| func | `def main()` |  |

### `email-to-calendar/scripts/utils/undo_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def find_last_undoable()` | Find and print the most recent undoable change ID. |
| func | `def list_undoable()` | Print all undoable changes. |
| func | `def mark_undone(change_id)` | Mark a change as undone. |
| func | `def main()` |  |

### `gantt-chart-builder/scripts/gantt_generator.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def validate_tasks(data)` |  |
| func | `def topological_sort(tasks)` |  |
| func | `def compute_critical_path(tasks)` |  |
| func | `def generate_html(project_name, tasks, critical_path, project_duration, start_date)` |  |
| func | `def main()` |  |

### `general-writing/scripts/check_chapter_quality.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def strip_markdown(text)` | Strip markdown syntax, keep prose only. |
| func | `def count_zh(text)` | Count CJK characters (Unified Ideographs + Extension A). |
| func | `def count_en(text)` | Count English words (tokens containing a letter). |
| func | `def detect_lang(text)` |  |
| func | `def count_em_dash(text)` | Count em-dash '——' occurrences in text. |
| func | `def calc_em_dash_density(em_dash_count, zh_char_count)` | Calculate em-dash density per 1000 Chinese chars. |
| func | `def scan_english_leakage(text)` | Find isolated English words (>=3 letters) embedded in Chinese prose. |
| func | `def check_file(file_path, min_words, max_em_dash_density, lang)` | Run all quality checks on a single file. Returns result dict. |
| func | `def main()` |  |

### `general-writing/scripts/check_wordcount.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def strip_markdown(text)` | Strip markdown syntax, keep prose only. |
| func | `def count_zh(text)` | Count CJK characters (Unified Ideographs + Extension A). |
| func | `def count_en(text)` | Count English words (tokens containing a letter). |
| func | `def detect_lang(text)` |  |
| func | `def main()` |  |

### `gitlab-cli-guide/scripts/post-inline-comment.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_token(host)` | Get GitLab token from env or glab config. Never prints or logs the token value. |
| func | `def validate_host(host)` | Enforce HTTPS to prevent token leakage over plaintext. |
| func | `def validate_project(project)` | Validate project path format: group/project or group/subgroup/project. |
| func | `def validate_file_path(file_path)` | Validate that a file path doesn't contain dangerous characters. |
| func | `def validate_body(body)` | Trim and cap comment body length. |
| func | `def validate_line(line)` | Line number must be a positive integer. |
| func | `def load_batch_file(path)` | Load and validate a batch comments JSON file. |
| func | `def get_mr_versions(token, host, project_id, mr_iid)` | Fetch current HEAD/START/BASE SHAs for an MR. |
| func | `def post_inline_comment(token, host, project_id, mr_iid, shas, file_path, line_number, body)` | Post a single inline comment on a MR diff using a JSON body. Returns (disc_id, is_inline) tuple. is_inline=False means GitLab rejected the p |
| func | `def main()` |  |

### `gitlab-cli-skills/scripts/post-inline-comment.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_token(host)` | Get GitLab token from env or glab config. Never prints or logs the token value. |
| func | `def validate_host(host)` | Enforce HTTPS to prevent token leakage over plaintext. |
| func | `def validate_project(project)` | Validate project path format: group/project or group/subgroup/project. |
| func | `def validate_file_path(file_path)` | Validate that a file path doesn't contain dangerous characters. |
| func | `def validate_body(body)` | Trim and cap comment body length. |
| func | `def validate_line(line)` | Line number must be a positive integer. |
| func | `def load_batch_file(path)` | Load and validate a batch comments JSON file. |
| func | `def get_mr_versions(token, host, project_id, mr_iid)` | Fetch current HEAD/START/BASE SHAs for an MR. |
| func | `def post_inline_comment(token, host, project_id, mr_iid, shas, file_path, line_number, body)` | Post a single inline comment on a MR diff using a JSON body. Returns (disc_id, is_inline) tuple. is_inline=False means GitLab rejected the p |
| func | `def main()` |  |

### `http-load-profiler/scripts/http_benchmark.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def validate_url(url)` |  |
| func | `def detect_tool(prefer)` |  |
| func | `def to_ms(value, unit)` |  |
| func | `def parse_wrk_output(output)` |  |
| func | `def parse_ab_output(output, csv_path)` |  |
| func | `def run_wrk(url, concurrency, duration, threads)` |  |
| func | `def run_ab(url, concurrency, duration, requests_per_step)` |  |
| func | `def find_inflection_points(results)` |  |
| func | `def find_optimal_concurrency(results, inflections)` |  |
| func | `def format_table(results, inflection_concurrencies)` |  |
| func | `def main()` |  |

### `http-load-tester/scripts/http_benchmark.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def validate_url(url)` |  |
| func | `def detect_tool(prefer)` |  |
| func | `def to_ms(value, unit)` |  |
| func | `def parse_wrk_output(output)` |  |
| func | `def parse_ab_output(output, csv_path)` |  |
| func | `def run_wrk(url, concurrency, duration, threads)` |  |
| func | `def run_ab(url, concurrency, duration, requests_per_step)` |  |
| func | `def find_inflection_points(results)` |  |
| func | `def find_optimal_concurrency(results, inflections)` |  |
| func | `def format_table(results, inflection_concurrencies)` |  |
| func | `def main()` |  |

### `incident-retrospective/scripts/generate_postmortem.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def parse_datetime(s)` | Parse an ISO-8601-ish datetime string into a datetime object. |
| func | `def format_duration(total_seconds)` | Format seconds into human-readable duration string. |
| func | `def compute_duration(start_str, end_str)` | Return human-readable duration between two datetime strings. |
| func | `def compute_hhmm_diff(t1, t2)` | Compute duration between two HH:MM strings (assumes same day or next day). |
| func | `def validate_data(data)` | Validate incident data and return list of warnings. |
| func | `def prompt_input(prompt_text, default, required)` | Read a line of input from the user with optional default. |
| func | `def prompt_list(prompt_text)` | Read multiple lines until empty line. |
| func | `def interactive_collect()` | Interactively collect incident data from the user. |
| func | `def render_markdown_zh(data, template)` | Render incident data as a Chinese Markdown postmortem. |
| func | `def render_markdown_en(data, template)` | Render incident data as an English Markdown postmortem. |
| func | `def main()` |  |

### `incident-review-guide/scripts/generate_postmortem.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def parse_datetime(s)` | Parse an ISO-8601-ish datetime string into a datetime object. |
| func | `def format_duration(total_seconds)` | Format seconds into human-readable duration string. |
| func | `def compute_duration(start_str, end_str)` | Return human-readable duration between two datetime strings. |
| func | `def compute_hhmm_diff(t1, t2)` | Compute duration between two HH:MM strings (assumes same day or next day). |
| func | `def validate_data(data)` | Validate incident data and return list of warnings. |
| func | `def prompt_input(prompt_text, default, required)` | Read a line of input from the user with optional default. |
| func | `def prompt_list(prompt_text)` | Read multiple lines until empty line. |
| func | `def interactive_collect()` | Interactively collect incident data from the user. |
| func | `def render_markdown_zh(data, template)` | Render incident data as a Chinese Markdown postmortem. |
| func | `def render_markdown_en(data, template)` | Render incident data as an English Markdown postmortem. |
| func | `def main()` |  |

### `landing-page-scaffold/scripts/generate_landing_page.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def e(text)` | HTML-escape user-provided text. |
| func | `def css_safe(text)` | Sanitize text for use inside <style>. Prevents </style> injection. |
| func | `def icon_svg(name, size)` | Return an inline SVG icon. Falls back to a circle if icon name is unknown. |
| func | `def deep_merge(base, override)` | Recursively merge override dict into base dict. |
| func | `def build_html(config)` | Build the complete HTML string from config. |
| func | `def load_config(args)` | Load config from file or CLI args, merge with defaults. |
| func | `def main()` |  |

### `localization-toolkit/scripts/i18n_audit.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def iter_source_files(root, exts)` |  |
| func | `def extract_keys(paths)` |  |
| func | `def flatten_json(obj, prefix)` |  |
| func | `def locale_name(path)` |  |
| func | `def has_plural_variant(key, key_set)` |  |
| func | `def load_locale(path)` |  |
| func | `def compute_missing(used, locale_keys)` |  |
| func | `def main()` |  |

### `log-diagnostic/scripts/analyze_logs.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def normalize_message(msg)` |  |
| func | `def detect_format(lines)` |  |
| func | `def parse_iso_time(ts)` |  |
| func | `def parse_json_line(line)` |  |
| func | `def parse_syslog_line(line)` |  |
| func | `def parse_nginx_line(line)` |  |
| func | `def is_error_level(level)` |  |
| func | `def parse_file(filepath, fmt, level_filter, since, until)` |  |
| func | `def cluster_errors(entries)` |  |
| func | `def compute_time_distribution(entries)` |  |
| func | `def bar_chart(value, max_value, width)` |  |
| func | `def print_report(entries, total_lines, parse_fail, fmt, clusters, hourly, daily, top_n)` |  |
| func | `def build_json_report(entries, total_lines, parse_fail, fmt, clusters, hourly, daily)` |  |
| func | `def main()` |  |

### `log-error-digest/scripts/analyze_logs.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def normalize_message(msg)` |  |
| func | `def detect_format(lines)` |  |
| func | `def parse_iso_time(ts)` |  |
| func | `def parse_json_line(line)` |  |
| func | `def parse_syslog_line(line)` |  |
| func | `def parse_nginx_line(line)` |  |
| func | `def is_error_level(level)` |  |
| func | `def parse_file(filepath, fmt, level_filter, since, until)` |  |
| func | `def cluster_errors(entries)` |  |
| func | `def compute_time_distribution(entries)` |  |
| func | `def bar_chart(value, max_value, width)` |  |
| func | `def print_report(entries, total_lines, parse_fail, fmt, clusters, hourly, daily, top_n)` |  |
| func | `def build_json_report(entries, total_lines, parse_fail, fmt, clusters, hourly, daily)` |  |
| func | `def main()` |  |

### `pricing-advisor/scripts/pricing_modeler.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def calculate_arpu(plans)` |  |
| func | `def project_revenue_at_price(base_customers, base_arpu, new_arpu, new_customers_monthly, churn_rate, months)` | Project MRR over N months at a new ARPU, assuming some churn from price change. |
| func | `def recommend_tier_structure(plans, competitor_prices, cogs, target_margin_pct)` | Recommend Good-Better-Best tier structure based on current state and competitors. |
| func | `def elasticity_estimate(trial_to_paid_pct, current_arpu)` | Rough price elasticity signal based on conversion rate. |
| func | `def print_report(result, inputs)` |  |
| func | `def main()` |  |

### `project-sizing-guide/scripts/estimate_calculator.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def validate_pert_task(task, idx)` |  |
| func | `def calc_pert(tasks)` |  |
| func | `def calc_tshirt(tasks)` |  |
| func | `def calc_fpa(components, hours_per_fp)` |  |
| func | `def parse_json_arg(value, arg_name)` |  |
| func | `def main()` |  |
| func | `def print_table(result)` |  |

### `py-perf-analyzer/scripts/perf_profile.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def run_cpu_profile(script_path, script_args, sort_key, top_n, threshold)` |  |
| func | `def run_memory_profile(script_path, script_args, top_n)` |  |
| func | `def run_combined_profile(script_path, script_args, sort_key, top_n, threshold)` |  |
| func | `def run_line_profile(script_path, script_args, functions, top_n)` |  |
| func | `def print_cpu_report(result)` |  |
| func | `def print_memory_report(result)` |  |
| func | `def print_line_report(result)` |  |
| func | `def print_suggestion(cpu_result)` | 根据 CPU 分析结果给出优化建议 |
| func | `def main()` |  |

### `route-to-openapi/scripts/generate_api_doc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def convert_path_params(path, framework)` | Convert framework path-param syntax to OpenAPI {param} format. |
| func | `def extract_docstring(node)` | Extract docstring from a Python function AST node. |
| func | `def annotation_to_str(node)` | Convert an AST annotation node to its string representation. |
| func | `def python_type_to_schema(type_str)` | Map a Python type-annotation string to an OpenAPI schema dict. |
| class | `class PythonExtractor` | Extract API routes from Python source files via AST. |
| class | `class JSExtractor` | Extract API routes from JS/TS files (Express.js). |
| class | `class GoExtractor` | Extract API routes from Go files (Gin, Echo). |
| func | `def build_openapi_spec(routes, title, version, description, servers)` |  |
| func | `def detect_framework(source_dir)` |  |
| func | `def scan_and_extract(source_dir, framework)` |  |
| func | `def to_yaml(obj, indent)` | Minimal YAML serializer sufficient for OpenAPI specs. |
| func | `def main()` |  |

### `seedance-video-generate/scripts/seedance_video_generate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SeedanceConfig` | Configuration for Seedance API. |
| class | `class SeedanceVideoGenerator` | Generator for Seedance videos. |
| func | `def generate_video(prompt, image_path, duration, resolution, style, motion_strength, seed, fps, output_dir, api_key)` | Generate video using Seedance API. |
| func | `def extend_video(video_path, prompt, extend_duration, output_dir, api_key)` | Extend existing video using Seedance API. |

### `seedream-image-generate/scripts/seedream_image_generate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SeedreamConfig` | Configuration for Seedream API. |
| class | `class SeedreamImageGenerator` | Generator for Seedream images. |
| func | `def generate_image(prompt, width, height, ratio, style, seed, negative_prompt, num_images, output_dir, api_key)` | Generate image using Seedream API. |

### `sql-insight/scripts/sql_query_helper.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SchemaExtractor` | Extract database schema for NL→SQL context. |
| class | `class QueryOptimizer` | Rule-based SQL optimization suggestions (13 rules). |
| class | `class ExplainInterpreter` | Parse and interpret EXPLAIN output for SQLite and PostgreSQL. |
| func | `def build_parser()` |  |
| func | `def main()` |  |

### `sql-tutor/scripts/sql_query_helper.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SchemaExtractor` | Extract database schema for NL→SQL context. |
| class | `class QueryOptimizer` | Rule-based SQL optimization suggestions (13 rules). |
| class | `class ExplainInterpreter` | Parse and interpret EXPLAIN output for SQLite and PostgreSQL. |
| func | `def build_parser()` |  |
| func | `def main()` |  |

### `sun-path/scripts/annual_sun_hours.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_shadow_polygon(lat, lon, dt_utc, width, depth, height, rotation)` | Return (sun_altitude_deg, shadow_polygon). If sun below horizon, returns (altitude, None). Shadow polygon is in same 2D plane as building (m |
| func | `def run_annual(lat, lon, width, depth, height, rotation, point_x, point_y, year, interval_minutes, tz_name)` | Run annual sampling. Returns (hours_sun, hours_shadow, hours_night), and list of (month, sun_h, shadow_h, night_h) for optional plotting. |
| func | `def main()` |  |

### `sun-path/scripts/comfort_calc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_saturation_vapor_pressure(temp_c)` |  |
| func | `def get_humidity_ratio(temp_c, rh_percent, pressure_pa)` |  |
| func | `def plot_psychrometric(temp, rh, output_file)` |  |

### `sun-path/scripts/plot_sunpath.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def generate_sunpath_diagram(lat, lon, output_file)` |  |

### `sun-path/scripts/shadow_calc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def calculate_shadow(lat, lon, time_str, width, depth, height, rotation, output_file)` |  |

### `sun-path/scripts/sun_calc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def calculate_sun_position(lat, lon, timezone_str)` |  |

### `sun-path/scripts/terrain_shadow.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def compute_shadow_grid(dem, transform, nodata, lat_deg, lon_deg, dt_utc, crs_is_geographic, step_pixels)` | Compute binary shadow (1=shadow, 0=sun) for DEM array. dem: 2D float array (height, width); row-major [row, col]. transform: rasterio Affine |
| func | `def main()` |  |

### `sunlight-analysis/scripts/annual_sun_hours.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_shadow_polygon(lat, lon, dt_utc, width, depth, height, rotation)` | Return (sun_altitude_deg, shadow_polygon). If sun below horizon, returns (altitude, None). Shadow polygon is in same 2D plane as building (m |
| func | `def run_annual(lat, lon, width, depth, height, rotation, point_x, point_y, year, interval_minutes, tz_name)` | Run annual sampling. Returns (hours_sun, hours_shadow, hours_night), and list of (month, sun_h, shadow_h, night_h) for optional plotting. |
| func | `def main()` |  |

### `sunlight-analysis/scripts/comfort_calc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_saturation_vapor_pressure(temp_c)` |  |
| func | `def get_humidity_ratio(temp_c, rh_percent, pressure_pa)` |  |
| func | `def plot_psychrometric(temp, rh, output_file)` |  |

### `sunlight-analysis/scripts/plot_sunpath.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def generate_sunpath_diagram(lat, lon, output_file)` |  |

### `sunlight-analysis/scripts/shadow_calc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def calculate_shadow(lat, lon, time_str, width, depth, height, rotation, output_file)` |  |

### `sunlight-analysis/scripts/sun_calc.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def calculate_sun_position(lat, lon, timezone_str)` |  |

### `sunlight-analysis/scripts/terrain_shadow.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def compute_shadow_grid(dem, transform, nodata, lat_deg, lon_deg, dt_utc, crs_is_geographic, step_pixels)` | Compute binary shadow (1=shadow, 0=sun) for DEM array. dem: 2D float array (height, width); row-major [row, col]. transform: rasterio Affine |
| func | `def main()` |  |


## Who imports this

**9** file(s) reference this package:

- **`runtime/core/`** · 3 file(s)
  - `runtime/core/cerebrum/_react_context_helpers.py`
  - `runtime/core/cerebrum/_react_execution_dispatch.py`
  - `runtime/core/cerebrum/react_parallel_dispatch.py`
- **`runtime/execution/`** · 3 file(s)
  - `runtime/execution/misc/capability_catalog.py`
  - `runtime/execution/misc/capability_permissions.py`
  - `runtime/execution/swarm/drive.py`
- **`runtime/platform/`** · 2 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/ui/health_router.py`
- **`runtime/sensing/`** · 1 file(s)
  - `runtime/sensing/gateway/_meta_skill_metadata.py`

