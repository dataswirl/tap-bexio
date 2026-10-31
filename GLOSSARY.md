# Glossary

Terms used in the code, tests and docs of tap-bexio.

| Term | Meaning |
|------|---------|
| **API generation** | Bexio serves three API versions side by side. **2.0** lists are bare arrays paged with `limit`/`offset`, timestamps are company-local without an offset. **3.0** is the same paging, sometimes with an `X-Total-Count` header, timestamps carry an offset. **4.0** pages by page number (`page`, `limit` or `per-page`), records sit under `data` or `results`, timestamps are UTC (`+0000`). |
| **Company timezone** | The `timezone` setting. Bexio 2.0 timestamps are in this zone with no offset, and every emitted timestamp is converted to it. |
| **Document** | A sales document: invoice, offer (quote), order or delivery. The 2.0 API calls them `kb_invoice`, `kb_offer`, `kb_order` and `kb_delivery`. |
| **Position** | A line of a document (article, custom, text, subtotal, discount, page break, subposition). It comes from the document detail response and has the primary key `(document_id, type, id)`. |
| **Parent / child stream** | A child stream runs once per parent record and gets the parent's `id` under the parent's `child_context_key` (e.g. `document_id`). |
| **Context** | The dict a child stream receives from its parent, or a partition's own keys. Keys that are in the child's schema are copied onto each record. |
| **Partition** | One slice of a stream with its own bookmark. Only `contacts` has partitions (`archived: false` / `true`). Child streams keep a single bookmark, not one per parent. |
| **Bookmark / replication key** | For incremental streams, the latest `updated_at` seen, stored in the Singer state. The next run starts from it, or from `start_date` when there is no bookmark yet. |
| **Search stream** | An incremental 2.0 stream. With a bookmark it sends `POST <path>/search` with `updated_at >= bookmark`, ordered by `id`. Without one it reads the plain list. |
| **Forbidden stream** | A stream Bexio answers with 403 because the token lacks a scope or the module is inactive. `forbidden_stream_behavior` decides whether to skip it or fail. |
| **Skipped partition** | A child request that returns 404 because the parent record was deleted mid-sync. Only that parent's child records are skipped. |
| **Business year** | The payroll year that absences are requested for (`businessYear`). The tap reads every year from `start_date` to today, or the last two years. |
| **Throttle** | Pausing before the next request when `RateLimit-Remaining` drops to 1. A 429 is instead retried after `RateLimit-Reset`. |
| **Golden snapshot** | `tests/golden/*.json`: the Singer messages full syncs emit against canned responses, used to prove refactors change no output. |
| **Auth mode** | How the tap authenticates: a **Personal Access Token** (`auth_token`, sent as-is) or **OAuth** (`client_id`, `client_secret`, `refresh_token`). Exactly one mode is configured; `BexioConfig.auth` is `TokenAuth` or `OAuthCredentials`. |
| **Refresh token** | The long-lived OAuth credential the tap trades at bexio's token endpoint for a 1-hour **access token** on each run, and again shortly before that token expires. Obtained once with `tap-bexio-auth`. |
| **Offline token** | A refresh token issued for the `offline_access` scope (`refresh_expires_in: 0`). It does not expire while used, but bexio revokes it after a long idle period. |
| **Token rotation** | bexio answering a refresh with a different refresh token. The tap uses the new one for the rest of the run and warns, since it cannot write it back to the config. |
