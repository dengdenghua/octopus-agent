# Native Reach production guide

Octopus Native Reach provides platform-aware search, structured reads, logged-in browser
handoff, batch evidence collection, persistent caching and operational health checks without
depending on the Agent Reach CLI.

## Supported platforms

| Platform | Search | Public read | Signed-in read |
|---|---|---|---|
| Web | SearXNG | HTTP extractor | Browser fallback |
| GitHub | GitHub API | Repositories, README, issues, PRs, comments | Token optional |
| YouTube | SearXNG | Metadata and subtitles through yt-dlp | Not normally required |
| Bilibili | SearXNG | Public video API | Not normally required |
| RSS | URL-based | feedparser or stdlib XML | Not required |
| Reddit, X, Xiaohongshu | SearXNG | Limited | Existing Chrome/Octopus browser session |
| Douyin, Doubao | SearXNG | Limited | Existing Chrome/Octopus browser session |
| Toutiao | SearXNG | Public article extractor | Browser fallback |

## Agent tools

- `platform_search`: platform-specific search with canonical URL deduplication and scoring.
- `platform_read`: structured URL reader. Pass `use_browser=true` for signed-in platforms.
- `platform_collect`: bounded batch collection and JSON/Markdown export.
- `platform_monitor`: creates a durable recurring collection in the existing cron store.
- `reach_doctor`: dependency, backend and login-requirement health report.

Recurring monitoring uses the existing `schedule_task` tool. The scheduled prompt should call
`platform_collect` with fixed queries and an output format. Collection files default to
`~/.octopus/data/reach/collections/`.

## Operations API

- `GET /api/reach/status`
- `GET /api/reach/collections`
- `GET /api/reach/collections/{name}`
- `POST /api/reach/collect`
- `DELETE /api/reach/cache`
- `DELETE /api/reach/collections/{name}`

Read endpoints require an authenticated user when authentication is enabled. Collection and
deletion endpoints additionally require the `admin` or `operator` role.

## Production configuration

Install the full adapter dependencies with `uv sync --extra reach`. Configure:

```dotenv
WEB_SEARCH_BACKEND=searxng
SEARXNG_URL=https://search.example.com
OCTOPUS_REACH_CACHE_PATH=~/.octopus/cache/reach.sqlite3
OCTOPUS_REACH_CACHE_MAX_ENTRIES=512
OCTOPUS_REACH_REQUESTS_PER_MINUTE=60
GITHUB_TOKEN=
```

The GitHub token can instead be stored in the operating-system keychain as
`reach.github_token`. Browser cookies stay in the browser profile and are not copied into
collection files or Octopus configuration.

## Reliability and security

Successful public reads are cached in SQLite and memory. HTTP connections retry transient
transport failures; a per-host sliding-window limiter prevents accidental request floods.
Failures return structured `error`, `repair_hint`, `requires_browser` and
`retry_after_seconds` fields where applicable. Collection filenames are server-generated and
API path validation prevents traversal outside the Reach data directory.
