# Notion assignment imports

PlanGuard supports `disabled`, `demo`, and `live` Notion modes.

## Demo mode

Set:

```text
NOTION_MODE=demo
```

Connect the clearly labelled demo workspace from the dashboard, choose the
Coursework source, map its properties, preview the rows, and import them. No
Notion account, credentials, or network request is used.

## Live OAuth configuration

Create a public Notion connection with read-content capability and register the
exact callback URI. Configure secrets outside source control:

```text
NOTION_MODE=live
NOTION_CLIENT_ID=...
NOTION_CLIENT_SECRET=...
NOTION_OAUTH_REDIRECT_URI=https://example.com/integrations/notion/callback
TOKEN_ENCRYPTION_KEY=...
```

PlanGuard uses Notion API version `2026-03-11`. OAuth state is random,
user-bound, expires after ten minutes, and is consumed once. Access and refresh
tokens use the same authenticated encryption boundary as Google Calendar and
are never rendered, serialized, or cached with import data.

## Import behavior

After connection, users choose an accessible Notion data source and map its
properties to PlanGuard fields. Title and deadline are required. Optional
fields use PlanGuard defaults when they are unmapped or invalid.

Imports are previewed before persistence. Every assignment belongs to the
signed-in user and stores `provider=notion` plus its Notion page ID. Re-imported
page IDs are skipped and reported as already imported, so Notion cannot
overwrite progress or edits made in PlanGuard.

PlanGuard caches only source metadata, its property schema, mapping, and the
last import summary. Raw Notion rows and unrelated workspace content are not
cached. Disconnecting removes credentials and source configuration but keeps
assignments already imported into PlanGuard.

Notion remains `Connected` until an import succeeds. During an import it is
`Syncing`; only a successful committed import changes it to `Synced` and records
the last successful time. Failed imports show a retry or reconnect action
without changing previously imported assignments.
