---
name: lark-tools
description: >
  Use when the user wants to interact with Lark/Feishu — send messages, manage Bitable/Base records,
  read/write documents, manage calendar, tasks, sheets, mail, wiki, meetings, or any Lark workspace operation.
  This skill uses `lark-cli` (official CLI from @larksuite/cli) via bash, NOT mcp_call.
tool_triggers:
  - tool: mcp_call
    args:
      action: search
      keyword: /lark|feishu|飞书/i
---

# Lark / Feishu Tools (via lark-cli)

Operate Lark/Feishu through `lark-cli` locally. Authorization is handled by the
Connector UI (credentials synced from MCP server to local machine automatically).

## Authorization

### Step 1 — Check current status

```bash
lark-cli auth status
```

### Step 2 — Handle result

| Result | Action |
|--------|--------|
| `tokenStatus: "valid"` | Proceed to business commands |
| `command not found` | lark-cli not installed — see Install section below |
| `not logged in` / `ok: false` | Guide user to **Settings → Connectors → Lark (Feishu) → Connect** |

**IMPORTANT**: When auth fails, always guide the user to the Connector UI first.
The Connector handles the full OAuth flow on the MCP server and automatically
syncs credentials (encrypted token files) to the local machine.

### Fallback: manual CLI setup

Only if the Connector is unavailable AND the user explicitly wants to set up locally.

**WARNING**: On macOS, lark-cli auth commands may fail due to Keychain access
restrictions in non-terminal processes. If you encounter `keychain unavailable`
or `operation not permitted`, the user MUST run auth commands in their own
Terminal.app (not through the agent).

```bash
# 1. Install
npm install -g @larksuite/cli

# 2. Configure app (user completes in browser)
lark-cli config init --new

# 3. Login (user completes in browser)
lark-cli auth login --recommend

# 4. Verify
lark-cli auth status
```

For steps 2 and 3: these commands block and output a URL. Run in background,
extract the URL, and present it to the user as a clickable link.

### Install lark-cli (if missing)

```bash
npm install -g @larksuite/cli
```

## Command Pattern

```
lark-cli <domain> +<shortcut> [--flags]     # Shortcuts (recommended)
lark-cli <domain> <resource> <action>        # API commands (1:1 with platform)
lark-cli api <METHOD> <path> --body '{...}'  # Raw API (2500+ endpoints)
```

**`--format` flag**: Most shortcuts support `--format json`. Some (like `calendar +create`) do NOT.
When in doubt, try with `--format json` first; if it fails with "unknown flag", omit it.

## Domain Reference

### Messaging (im)

**Shortcuts**: `+chat-create`, `+chat-messages-list`, `+chat-search`, `+chat-update`,
`+messages-mget`, `+messages-reply`, `+messages-resources-download`, `+messages-search`,
`+messages-send`, `+threads-messages-list`

```bash
# Search group chats by keyword (requires --query or --member-ids)
lark-cli im +chat-search --query "项目" --format json

# Search chats by member
lark-cli im +chat-search --member-ids "ou_xxx" --format json

# Create group chat (bot-only, default --as bot)
lark-cli im +chat-create --name "Project Alpha" --users "ou_xxx,ou_yyy" --format json

# Update group chat name/description
lark-cli im +chat-update --chat-id "oc_xxx" --name "New Name" --format json

# List messages in a chat (by chat-id OR user-id for P2P)
lark-cli im +chat-messages-list --chat-id "oc_xxx" --format json
lark-cli im +chat-messages-list --user-id "ou_xxx" --format json
lark-cli im +chat-messages-list --chat-id "oc_xxx" --start "2026-04-01T00:00:00+08:00" --end "2026-04-02T00:00:00+08:00" --format json

# Search messages (user-only, requires scope search:message)
lark-cli im +messages-search --query "quarterly report" --format json
lark-cli im +messages-search --query "report" --chat-id "oc_xxx" --start "2026-04-01T00:00:00+08:00" --format json

# Batch get messages by IDs
lark-cli im +messages-mget --message-ids "om_xxx,om_yyy" --format json

# Send message (bot-only, default --as bot)
lark-cli im +messages-send --chat-id "oc_xxx" --text "Hello team!"
lark-cli im +messages-send --user-id "ou_xxx" --markdown "**Important** update"
lark-cli im +messages-send --chat-id "oc_xxx" --image "./photo.png"
lark-cli im +messages-send --chat-id "oc_xxx" --file "./report.pdf"

# Reply to a message (bot-only, default --as bot)
lark-cli im +messages-reply --message-id "om_xxx" --text "Got it!"
lark-cli im +messages-reply --message-id "om_xxx" --text "Thread reply" --reply-in-thread

# List messages in a thread
lark-cli im +threads-messages-list --thread "om_xxx" --format json

# Download images/files from a message
lark-cli im +messages-resources-download --message-id "om_xxx" --file-key "img_xxx" --type image --output ./downloads/
```

### Calendar

**Shortcuts**: `+agenda`, `+create`, `+freebusy`, `+suggestion`

**Note**: `+create` does NOT support `--format` flag.

```bash
# View today's agenda
lark-cli calendar +agenda --format json

# View specific date range
lark-cli calendar +agenda --start "2026-04-01T00:00:00+08:00" --end "2026-04-03T23:59:59+08:00" --format json

# Create event (NO --format flag)
lark-cli calendar +create --summary "Weekly Sync" \
  --start "2026-04-01T10:00:00+08:00" \
  --end "2026-04-01T11:00:00+08:00" \
  --description "Team sync meeting" \
  --attendee-ids "ou_xxx,ou_yyy"

# Create recurring event
lark-cli calendar +create --summary "Daily Standup" \
  --start "2026-04-01T09:00:00+08:00" \
  --end "2026-04-01T09:30:00+08:00" \
  --rrule "FREQ=DAILY;COUNT=10"

# Check free/busy
lark-cli calendar +freebusy --user-id "ou_xxx" --format json
lark-cli calendar +freebusy --start "2026-04-01T00:00:00+08:00" --end "2026-04-01T23:59:59+08:00" --format json

# Suggest meeting times
lark-cli calendar +suggestion --attendee-ids "ou_xxx,ou_yyy" --duration-minutes 30 --format json
```

### Documents (docs)

**Shortcuts**: `+create`, `+fetch`, `+search`, `+update`, `+media-download`, `+media-insert`, `+whiteboard-update`

```bash
# Create document (NO --format flag)
lark-cli docs +create --title "Meeting Notes" --markdown "# Summary\n- Item 1"

# Create in specific folder or wiki
lark-cli docs +create --title "Notes" --markdown "# Content" --folder-token "folXXX"
lark-cli docs +create --title "Wiki Page" --markdown "# Content" --wiki-space "my_library"

# Fetch/read document content
lark-cli docs +fetch --doc "doccnXXXXXX" --format json
lark-cli docs +fetch --doc "https://xxx.feishu.cn/docx/xxxxx" --format json

# Search docs, wiki, spreadsheets
lark-cli docs +search --query "product roadmap" --format json

# Update document (multiple modes: append, overwrite, replace_range, etc.)
lark-cli docs +update --doc "doccnXXXXXX" --markdown "# New section" --mode append
lark-cli docs +update --doc "doccnXXXXXX" --markdown "# Replaced" --mode overwrite
lark-cli docs +update --doc "doccnXXXXXX" --new-title "Updated Title"

# Insert image/file into document
lark-cli docs +media-insert --doc "doccnXXXXXX" --file "./chart.png" --type image --caption "Q1 Results"

# Download media from document
lark-cli docs +media-download --token "file_xxx" --output ./downloads/
```

### Base / Bitable (base)

**Key shortcuts**: `+record-list`, `+record-get`, `+record-upsert`, `+record-delete`,
`+field-list`, `+field-create`, `+table-list`, `+table-create`, `+data-query`

Also supports: views, forms, dashboards, roles, workflows, advanced permissions, attachments.

```bash
# List tables in a base
lark-cli base +table-list --base-token "bascnXXX"

# List fields in a table
lark-cli base +field-list --base-token "bascnXXX" --table-id "tblXXX"

# List records
lark-cli base +record-list --base-token "bascnXXX" --table-id "tblXXX"

# Get a specific record
lark-cli base +record-get --base-token "bascnXXX" --table-id "tblXXX" --record-id "recXXX"

# Create or update a record (upsert)
lark-cli base +record-upsert --base-token "bascnXXX" --table-id "tblXXX" \
  --json '{"fields":{"Name":"Alice","Score":95}}'

# Update existing record
lark-cli base +record-upsert --base-token "bascnXXX" --table-id "tblXXX" \
  --record-id "recXXX" --json '{"fields":{"Score":100}}'

# Delete a record (requires --yes for confirmation)
lark-cli base +record-delete --base-token "bascnXXX" --table-id "tblXXX" --record-id "recXXX" --yes

# Query with DSL (aggregation, filter, sort)
lark-cli base +data-query --base-token "bascnXXX" \
  --dsl '{"table_id":"tblXXX","filter":{"conjunction":"and","conditions":[{"field_name":"Status","operator":"is","value":["Active"]}]}}'

# Create table with fields
lark-cli base +table-create --base-token "bascnXXX" --name "Tasks" \
  --fields '[{"field_name":"Title","type":1},{"field_name":"Status","type":3}]'

# Upload attachment to a record
lark-cli base +record-upload-attachment --base-token "bascnXXX" --table-id "tblXXX" ...
```

### Sheets

**Shortcuts**: `+read`, `+write`, `+append`, `+create`, `+find`, `+info`, `+export`

Supports `--spreadsheet-token` or `--url` to identify the spreadsheet.

```bash
# Get spreadsheet info
lark-cli sheets +info --spreadsheet-token "shtcnXXX"
lark-cli sheets +info --url "https://xxx.feishu.cn/sheets/shtcnXXX"

# Read data
lark-cli sheets +read --spreadsheet-token "shtcnXXX" --range "Sheet1!A1:D50"

# Write data (overwrite mode)
lark-cli sheets +write --spreadsheet-token "shtcnXXX" --range "Sheet1!A1" \
  --values '[["Name","Score"],["Alice",95]]'

# Append rows
lark-cli sheets +append --spreadsheet-token "shtcnXXX" --range "Sheet1!A1" \
  --values '[["Bob",88]]'

# Create spreadsheet
lark-cli sheets +create --title "Q2 Report" --headers '["Name","Score","Grade"]'

# Find cells
lark-cli sheets +find --spreadsheet-token "shtcnXXX" --find "keyword" --range "Sheet1!A1:Z100"

# Export spreadsheet
lark-cli sheets +export --spreadsheet-token "shtcnXXX" --file-extension xlsx --output-path ./report.xlsx
```

### Drive

**Shortcuts**: `+download`, `+upload`, `+add-comment`

```bash
# Upload file
lark-cli drive +upload --file "./report.pdf" --folder-token "folXXX" --name "Q2 Report.pdf"

# Download file
lark-cli drive +download --file-token "fileXXX" --output ./downloads/

# Add comment to a document
lark-cli drive +add-comment --doc "doccnXXXXXX" --content '[{"type":"text","text":"Please review"}]'
```

**Note**: There is no `+search` shortcut for drive. Use `docs +search` to search files, or use the raw API:
```bash
lark-cli api POST /open-apis/suite/docs-api/search/object --data '{"search_key":"budget 2026","count":20}'
```

### Tasks

**Shortcuts**: `+create`, `+complete`, `+get-my-tasks`, `+update`, `+assign`, `+comment`,
`+reopen`, `+reminder`, `+followers`, `+tasklist-create`, `+tasklist-members`, `+tasklist-task-add`

```bash
# Create task
lark-cli task +create --summary "Review PR #42" --due "2026-04-05T18:00:00+08:00" --format json
lark-cli task +create --summary "Weekly report" --due "date:2026-04-05" --assignee "ou_xxx" --format json

# List my tasks
lark-cli task +get-my-tasks --format json
lark-cli task +get-my-tasks --query "review" --format json
lark-cli task +get-my-tasks --complete --format json

# Complete / reopen task
lark-cli task +complete --task-id "taskXXX" --format json
lark-cli task +reopen --task-id "taskXXX" --format json

# Update task
lark-cli task +update --task-id "taskXXX" --summary "New title" --due "relative:+2d" --format json

# Assign / unassign
lark-cli task +assign --task-id "taskXXX" --add "ou_xxx,ou_yyy" --format json
lark-cli task +assign --task-id "taskXXX" --remove "ou_xxx" --format json

# Add comment
lark-cli task +comment --task-id "taskXXX" --content "LGTM" --format json

# Set reminder
lark-cli task +reminder --task-id "taskXXX" --set "15m" --format json
lark-cli task +reminder --task-id "taskXXX" --remove --format json

# Manage followers
lark-cli task +followers --task-id "taskXXX" --add "ou_xxx" --format json

# Create tasklist with tasks
lark-cli task +tasklist-create --name "Sprint 12" --format json
```

### Mail

**Shortcuts**: `+triage`, `+message`, `+messages`, `+send`, `+reply`, `+reply-all`,
`+forward`, `+draft-create`, `+draft-edit`, `+thread`, `+watch`

```bash
# List/triage emails (table format by default)
lark-cli mail +triage
lark-cli mail +triage --query "budget report" --max 50
lark-cli mail +triage --filter '{"folder":"INBOX","from":["alice@example.com"]}' --format json

# Read single email
lark-cli mail +message --message-id "mailXXX" --format json

# Read email thread
lark-cli mail +thread --thread-id "threadXXX" --format json

# Compose & send email (saves as draft by default; --confirm-send to send)
lark-cli mail +send --to "user@company.com" --subject "Follow up" --body "Please review."
lark-cli mail +send --to "user@company.com" --subject "Report" --body "<b>Important</b>" --confirm-send

# Reply to email
lark-cli mail +reply --message-id "mailXXX" --body "Thanks, received."
lark-cli mail +reply --message-id "mailXXX" --body "Done" --confirm-send

# Reply all
lark-cli mail +reply-all --message-id "mailXXX" --body "Noted, will follow up."

# Forward email
lark-cli mail +forward --message-id "mailXXX" --to "boss@company.com" --body "FYI"

# Create draft from scratch
lark-cli mail +draft-create --to "user@company.com" --subject "Draft" --body "WIP" --format json

# Edit existing draft
lark-cli mail +draft-edit --draft-id "draftXXX" --inspect
lark-cli mail +draft-edit --draft-id "draftXXX" --set-subject "New Subject"

# Watch for incoming mail (WebSocket, long-running)
lark-cli mail +watch --format data
```

### Wiki

**Note**: Wiki has NO shortcuts. Use raw API commands or `docs +search` / `docs +fetch` for wiki content.

```bash
# Search wiki (via docs +search)
lark-cli docs +search --query "onboarding guide" --format json

# Read wiki node (via docs +fetch with wiki URL)
lark-cli docs +fetch --doc "https://xxx.feishu.cn/wiki/xxxxx" --format json

# List wiki spaces (raw API)
lark-cli wiki spaces list --format json
```

### Contact

**Shortcuts**: `+get-user`, `+search-user`

```bash
# Get current user info
lark-cli contact +get-user --format json

# Get specific user
lark-cli contact +get-user --user-id "ou_xxx" --format json

# Search users
lark-cli contact +search-user --query "Alice" --format json
```

### Video Conference / Meetings (vc)

**Shortcuts**: `+search`, `+notes`

```bash
# Search meeting records
lark-cli vc +search --query "standup" --format json
lark-cli vc +search --start "2026-04-01" --end "2026-04-02" --format json
lark-cli vc +search --participant-ids "ou_xxx" --format json

# Get meeting notes (by meeting ID, minute token, or calendar event ID)
lark-cli vc +notes --meeting-ids "meetingXXX" --format json
lark-cli vc +notes --calendar-event-ids "eventXXX" --format json
lark-cli vc +notes --minute-tokens "minXXX" --output-dir ./notes/
```

## Advanced Usage

### Pagination

```bash
--page-all            # Auto-paginate all pages
--page-limit 5        # Max pages to fetch (default 10)
--page-delay 500      # 500ms between pages (default 200)
--page-size 20        # Items per page
```

### Dry Run

```bash
lark-cli im +messages-send --chat-id "oc_xxx" --text "hello" --dry-run
```

### Identity Switching

```bash
--as user   # Logged-in user identity (default for most commands)
--as bot    # App/bot identity (default for +messages-send, +messages-reply, +chat-create)
```

### Schema Inspection

```bash
lark-cli schema                          # List all API methods
lark-cli schema im.messages.create       # Inspect specific method
```

### Health Check

```bash
lark-cli doctor    # Check config, auth, and connectivity
```

## Error Handling

| Error | Fix |
|-------|-----|
| `command not found: lark-cli` | `npm install -g @larksuite/cli` |
| `not configured` / `no app configured` | Guide user: **Settings → Connectors → Lark → Connect** |
| `not logged in` / `token expired` | Guide user: **Settings → Connectors → Lark → Connect** |
| `missing required scope(s): xxx` | Need additional scopes — guide user to re-auth with needed scope |
| `permission denied` / `scope missing` | Need additional scopes: `lark-cli auth login --scope "xxx"` (in user's Terminal) |
| `unknown flag: --format` | This shortcut doesn't support `--format`; omit the flag |
| `keychain unavailable` / `operation not permitted` | macOS Keychain restriction. Use Connector flow (bypasses Keychain) or run in user's Terminal.app |
| `rate limited` | Wait a few seconds and retry |

## Rules

1. **Check auth first** — run `lark-cli auth status` before any business command.
2. **Connector-first for auth** — when auth fails, guide users to **Settings → Connectors → Lark**, not terminal commands.
3. **Use `--format json` when supported** — not all shortcuts support it (e.g. `calendar +create`). If you get "unknown flag", retry without it.
4. **Confirm before sending** — always confirm content/recipients before `+messages-send`, `+send` (mail), or any create/update operation.
5. **Use shortcuts (+)** — prefer `+shortcut` commands; they have smart defaults and validation.
6. **Summarize results** — present human-readable summaries, not raw JSON. Show raw output only when asked or for debugging.
7. **Dry-run destructive ops** — use `--dry-run` before send/create/delete.
8. **Don't attempt auth in agent process on macOS** — Keychain and file system restrictions will cause failures. Always delegate auth to the Connector UI or the user's Terminal.
9. **Bot vs User identity** — `+messages-send`, `+messages-reply`, `+chat-create` default to `--as bot`. Most other shortcuts default to `--as user`. Be aware of which identity is required.
