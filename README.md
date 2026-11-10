# tap-bexio

Singer tap for [Bexio](https://www.bexio.com/), built with the [Meltano Singer SDK](https://sdk.meltano.com).

Supports Python 3.12, 3.13 and 3.14.

## Configuration

| Setting                     | Required | Default                 | Description |
|-----------------------------|----------|-------------------------|-------------|
| `auth_token`                | no       |                         | Bexio Personal Access Token. Leave empty when using OAuth. |
| `client_id`                 | no       |                         | Client ID of the bexio developer portal app (OAuth). |
| `client_secret`             | no       |                         | Client secret of the bexio developer portal app (OAuth). |
| `refresh_token`             | no       |                         | Offline refresh token, exchanged for an access token on every run. Get one with `tap-bexio-auth`. |
| `oauth_token_url`           | no       | `https://auth.bexio.com/realms/bexio/protocol/openid-connect/token` | bexio OpenID Connect token endpoint. |
| `start_date`                | no       |                         | Lower bound of `updated_at` for incremental streams on the first sync; also the `from` date of `journal` and the first business year of `payroll_absences`. Without it, the first sync reads everything. |
| `api_url`                   | no       | `https://api.bexio.com` | Base URL of the Bexio API. |
| `user_agent`                | no       |                         | `User-Agent` header sent with every request. |
| `page_size`                 | no       | `500`                   | Records per request (max 2000; 500 for 4.0 purchase endpoints). |
| `timezone`                  | no       | `Europe/Zurich`         | Company timezone: that of Bexio's offset-less 2.0 timestamps, used to build the search filter. Dates are emitted as `YYYY-MM-DD`, taking the day in this timezone. |
| `output_timezone`           | no       | `UTC`                   | Timezone all timestamps are emitted in, as ISO 8601 (`2026-10-28T14:25:39+00:00`). A timezone with summer time gives two offsets (`+01:00` and `+02:00` for `Europe/Zurich`), which some targets reject in one column. |
| `forbidden_stream_behavior` | no       | `skip`                  | On HTTP 403 (missing scope or inactive module): `skip` logs a warning and continues, `fail` stops the sync. |

Set either `auth_token` or all of `client_id`, `client_secret` and `refresh_token`.

### Authentication

**Personal Access Token**: create one in bexio and set `auth_token`.

**OAuth (OpenID Connect)**: for an app registered in the
[bexio developer portal](https://developer.bexio.com/) with a redirect URL on this machine
(e.g. `http://localhost:8080/callback`):

1. Log in once and capture a refresh token:

   ```bash
   TAP_BEXIO_CLIENT_ID=... TAP_BEXIO_CLIENT_SECRET=... \
     uv run tap-bexio-auth --redirect-uri http://localhost:8080/callback
   ```

   This opens the browser, receives the redirect on the local port, and prints the
   `meltano config tap-bexio set refresh_token ...` command. `--scopes` overrides the
   requested scopes (default: `openid offline_access` plus the read scopes the streams use);
   `--json` prints the full token response.
2. Store `client_id`, `client_secret` and `refresh_token` with `meltano config tap-bexio set`
   (they go to `.env`, not `meltano.yml`).

On every run the tap exchanges the refresh token for an access token (valid 1 hour) and
refreshes it during long syncs. The `offline_access` refresh token does not expire while it
is used, but bexio revokes offline tokens that stay unused for its offline-idle period, so
run a sync at least monthly or log in again. If bexio ever issues a new refresh token the
tap logs a warning; update the setting if the old one stops working.

Settings can also be provided as environment variables (`TAP_BEXIO_AUTH_TOKEN`, ...) with `--config=ENV`.

API reference: <https://docs.bexio.com/>

Terms such as document, position, partition and search stream are defined in
[GLOSSARY.md](GLOSSARY.md).

## Streams

Incremental streams filter with `POST <path>/search` on `updated_at >= bookmark`. They fall
back to the plain list endpoint when there is neither state nor `start_date`. Child streams
run once per parent record, so on incremental runs they only re-read changed documents.

This affects the children of incremental parents: `contact_additional_addresses` (of
`contacts`), `invoice_positions`, `invoice_payments`, `invoice_comments`,
`invoice_reminders`, `offer_positions`, `offer_comments`, `order_positions` and
`order_comments`. Two consequences:

- A child record added or changed without bumping the parent's `updated_at` (for example
  an address added to a contact, or a payment recorded on an invoice, if Bexio does not
  touch the parent) is not picked up until the parent changes for another reason.
- Deleted child records are never removed downstream, since the tap only emits what the
  API returns.

To pick up both, run a full refresh periodically (e.g. `meltano run --full-refresh
tap-bexio <loader>`, or clear the state), with a target that replaces tables on full syncs.

Document positions come from the document detail endpoint (one request per document,
covering every position type) and have the primary key `(document_id, type, id)`.

| Stream | Endpoint | Replication | Parent |
|--------|----------|-------------|--------|
| `account_groups` | `/2.0/account_groups` | full |  |
| `accounts` | `/2.0/accounts` | full |  |
| `articles` | `/2.0/article` | full |  |
| `bank_accounts` | `/3.0/banking/accounts` | full |  |
| `bill_outgoing_payments` | `/4.0/purchase/outgoing-payments` | full | bills |
| `bills` | `/4.0/purchase/bills` | full |  |
| `business_activities` | `/2.0/client_service` | full |  |
| `business_years` | `/3.0/accounting/business_years` | full |  |
| `calendar_years` | `/3.0/accounting/calendar_years` | full |  |
| `communication_types` | `/2.0/communication_kind` | full |  |
| `company_profile` | `/2.0/company_profile` | full |  |
| `contact_additional_addresses` | `/2.0/contact/{contact_id}/additional_address` | full | contacts |
| `contact_groups` | `/2.0/contact_group` | full |  |
| `contact_relations` | `/2.0/contact_relation` | incremental |  |
| `contact_sectors` | `/2.0/contact_branch` | full |  |
| `contact_types` | `/2.0/contact_type` | full |  |
| `contacts` | `/2.0/contact` | incremental |  |
| `countries` | `/2.0/country` | full |  |
| `currencies` | `/3.0/currencies` | full |  |
| `currency_exchange_rates` | `/3.0/currencies/{currency_id}/exchange_rates` | full | currencies |
| `deliveries` | `/2.0/kb_delivery` | full |  |
| `delivery_positions` | `/2.0/kb_delivery/{document_id}` | full | deliveries |
| `document_settings` | `/2.0/kb_item_setting` | full |  |
| `document_templates` | `/3.0/document_templates` | full |  |
| `expenses` | `/4.0/expenses` | full |  |
| `fictional_users` | `/3.0/fictional_users` | full |  |
| `files` | `/3.0/files` | full |  |
| `invoice_comments` | `/2.0/kb_invoice/{document_id}/comment` | full | invoices |
| `invoice_payments` | `/2.0/kb_invoice/{document_id}/payment` | full | invoices |
| `invoice_positions` | `/2.0/kb_invoice/{document_id}` | full | invoices |
| `invoice_reminders` | `/2.0/kb_invoice/{document_id}/kb_reminder` | full | invoices |
| `invoices` | `/2.0/kb_invoice` | incremental |  |
| `journal` | `/3.0/accounting/journal` | full |  |
| `languages` | `/2.0/language` | full |  |
| `manual_entries` | `/3.0/accounting/manual_entries` | full |  |
| `manual_entry_files` | `/3.0/accounting/manual_entries/{manual_entry_id}/files` | full | manual_entries |
| `notes` | `/2.0/note` | full |  |
| `offer_comments` | `/2.0/kb_offer/{document_id}/comment` | full | offers |
| `offer_positions` | `/2.0/kb_offer/{document_id}` | full | offers |
| `offers` | `/2.0/kb_offer` | incremental |  |
| `order_comments` | `/2.0/kb_order/{document_id}/comment` | full | orders |
| `order_positions` | `/2.0/kb_order/{document_id}` | full | orders |
| `orders` | `/2.0/kb_order` | incremental |  |
| `payment_types` | `/2.0/payment_type` | full |  |
| `payments` | `/4.0/banking/payments` | full |  |
| `payroll_absences` | `/4.0/payroll/employees/{employee_id}/absences` | full | payroll_employees |
| `payroll_employees` | `/4.0/payroll/employees` | full |  |
| `permissions` | `/3.0/permissions` | full |  |
| `project_milestones` | `/3.0/projects/{project_id}/milestones` | full | projects |
| `project_packages` | `/3.0/projects/{project_id}/packages` | full | projects |
| `project_states` | `/2.0/pr_project_state` | full |  |
| `project_types` | `/2.0/pr_project_type` | full |  |
| `projects` | `/2.0/pr_project` | full |  |
| `purchase_orders` | `/3.0/purchase_orders` | full |  |
| `salutations` | `/2.0/salutation` | full |  |
| `stock_areas` | `/2.0/stock` | full |  |
| `stock_locations` | `/2.0/stock_place` | full |  |
| `task_priorities` | `/2.0/todo_priority` | full |  |
| `task_statuses` | `/2.0/todo_status` | full |  |
| `tasks` | `/2.0/task` | full |  |
| `taxes` | `/3.0/taxes` | full |  |
| `timesheet_statuses` | `/2.0/timesheet_status` | full |  |
| `timesheets` | `/2.0/timesheet` | full |  |
| `titles` | `/2.0/title` | full |  |
| `units` | `/2.0/unit` | full |  |
| `users` | `/3.0/users` | full |  |
| `vat_periods` | `/3.0/accounting/vat_periods` | full |  |

Notes:
- `contacts` syncs active and archived contacts as two partitions with separate bookmarks.
  Bexio's `show_archived=true` returns only archived contacts. Records carry an `archived` flag.
- `contact_types` uses the legacy `/2.0/contact_type` endpoint, which is no longer in the
  API reference.
- `payments` uses the 4.0 banking endpoint; the 3.0 payments endpoints are deprecated.
- `payroll_*` streams need the payroll module; without it they return 403 (see
  `forbidden_stream_behavior`).
- Without `start_date`, `payroll_absences` reads the current and previous business year.
- Rate limits: when `RateLimit-Remaining` drops to 1, the tap sleeps until `RateLimit-Reset`
  before the next request. A 429 is retried after `RateLimit-Reset` (60 s if the header is
  missing); 5xx and network errors are retried every 10 s. Each request gets 8 attempts.

## Usage

Copy [.env.example](.env.example) to `.env` (git-ignored) and set either
`TAP_BEXIO_AUTH_TOKEN` or the three OAuth variables. Other settings follow the same
pattern (`TAP_BEXIO_START_DATE`, `TAP_BEXIO_PAGE_SIZE`, ...). With `--config ENV` the SDK
loads the nearest `.env` (searching upward from the working directory) and reads the
`TAP_BEXIO_*` variables.

```bash
tap-bexio --about
tap-bexio --config ENV --discover > catalog.json
tap-bexio --config ENV --catalog catalog.json
```

With Meltano:

```bash
meltano invoke tap-bexio --discover
meltano run tap-bexio target-jsonl
```

### Installing in another Meltano project

The tap is not on PyPI; install it from the public GitHub repository. Pin a tag so
installs are reproducible:

```yaml
plugins:
  extractors:
    - name: tap-bexio
      namespace: tap_bexio
      repo: https://github.com/dataswirl/tap-bexio
      pip_url: git+https://github.com/dataswirl/tap-bexio.git@v0.1.0
      capabilities:
        - state
        - catalog
        - discover
        - about
        - stream-maps
        - structured-logging
      settings:
        - name: auth_token
          kind: string
          sensitive: true
        - name: client_id
          kind: string
        - name: client_secret
          kind: string
          sensitive: true
        - name: refresh_token
          kind: string
          sensitive: true
        - name: oauth_token_url
          kind: string
        - name: start_date
          kind: date_iso8601
        - name: api_url
          kind: string
        - name: user_agent
          kind: string
        - name: page_size
          kind: integer
        - name: timezone
          kind: string
        - name: output_timezone
          kind: string
        - name: forbidden_stream_behavior
          kind: options
          options:
            - label: Skip stream
              value: skip
            - label: Fail sync
              value: fail
      settings_group_validation:
        - [auth_token]
        - [client_id, client_secret, refresh_token]
```

Then `meltano install extractor tap-bexio` and set the token with
`meltano config tap-bexio set auth_token <token>` (or `TAP_BEXIO_AUTH_TOKEN`), or the OAuth
settings as described under [Authentication](#authentication).

To upgrade, push a new tag, bump it in `pip_url`, and run
`meltano install extractor tap-bexio` again.

## Development

This project uses [uv](https://docs.astral.sh/uv/), [ruff](https://docs.astral.sh/ruff/)
and [ty](https://docs.astral.sh/ty/). Dependency resolution applies a 2-week cooldown
(`tool.uv.exclude-newer = "2 weeks"`): package versions published in the last 14 days are ignored.

```bash
uv sync
uv run pre-commit install
uv run ruff check && uv run ruff format --check
uv run ty check
uv run pytest
```

Integration tests (`tests/test_core.py`) run against the live API only when
`TAP_BEXIO_AUTH_TOKEN` is set.

### Test data

`scripts/audit_sync.py` checks a live sync against the schemas. It lists schema
violations, fields the API returns that the schema lacks (the SDK silently drops them),
and schema fields no record contains. It prints field names and types only:

```bash
uv run tap-bexio --config ENV > sync.out 2> sync.err
uv run scripts/audit_sync.py sync.out sync.err
```

### Schemas

Stream schemas in `src/tap_bexio/schemas/` are generated from the OpenAPI spec embedded in
<https://docs.bexio.com/>. To refresh them after an API change:

```bash
uv run scripts/generate_schemas.py            # downloads the docs page
uv run scripts/generate_schemas.py docs.html  # or use a saved copy
```

New streams need an entry in `ENDPOINTS` in the script and a stream class in
`src/tap_bexio/streams/`. Fields the live API returns but the spec omits go in
`SCHEMA_PATCHES`. Otherwise the SDK drops them and logs "Properties ... not found in catalog schema".
