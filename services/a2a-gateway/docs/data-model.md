# Data model

PostgreSQL, drizzle-orm (convention: `teams-mcp`). Every table has `company_id`, `created_at`, `updated_at`; all queries filter on `company_id`. Ids are `typeid` strings with table prefixes.

```mermaid
%%{init: {'theme': 'neutral'}}%%
erDiagram
    publications ||--o{ contexts : "inbound"
    connections ||--o{ executions : "outbound"
    contexts ||--o{ tasks : ""
    tasks ||--o{ artifacts : ""
    tasks ||--o{ push_notification_configs : ""
    executions ||--o{ remote_contexts : ""

    publications {
        text id PK
        text company_id
        text assistant_id UK
        bool enabled
        jsonb card_overrides
        jsonb skills
        int version
        text created_by_user_id
        timestamptz disabled_at
    }
    connections {
        text id PK
        text company_id
        text name
        text agent_card_url
        jsonb agent_card_snapshot
        jsonb negotiated_capabilities
        text credential_type
        bytea credential_ciphertext
        int version
        timestamptz last_verified_at
        text last_error
    }
    contexts {
        text id PK "A2A contextId"
        text company_id
        text user_id
        text publication_id FK
        text chat_id UK
    }
    tasks {
        text id PK "A2A taskId"
        text company_id
        text user_id
        text context_id FK
        text state
        text user_message_id UK
        text assistant_message_id
        text elicitation_id
        jsonb task_snapshot
        timestamptz status_timestamp
        timestamptz expires_at
    }
    artifacts {
        text id PK
        text task_id FK
        text company_id
        text kind "text|data|file"
        text content_id "Unique content for files"
        jsonb artifact_snapshot
    }
    push_notification_configs {
        text id PK
        text task_id FK
        text company_id
        text url
        bytea auth_ciphertext
        int failures
    }
    executions {
        text id PK
        text company_id
        text user_id
        text connection_id FK
        text assistant_id
        text chat_id
        text user_message_id UK
        text assistant_message_id
        text remote_task_id
        text state
        jsonb correlation
        text elicitation_id
        timestamptz deadline_at
        text last_error
    }
    remote_contexts {
        text id PK
        text company_id
        text connection_id FK
        text chat_id UK
        text remote_context_id
    }
```

## Invariants

- `publications.assistant_id` unique per company; publishing is refused when core reports `executionProvider = A2A` (checked on write and re-checked by reconcile).
- `contexts.chat_id` unique; `tasks.user_message_id` unique; `executions.user_message_id` unique → idempotent retries never start a second run.
- Task visibility = `(company_id, user_id)`. `ListTasks` paginates by `(status_timestamp desc, id desc)` like the SDK in-memory store.
- Exactly one task per context may be non-terminal (partial unique index on `context_id where state not in terminal`).
- `credential_ciphertext` / `auth_ciphertext` are AES-GCM via `@unique-ag/aes-gcm-encryption`; plaintext never leaves the `CredentialVault`.
- `version` on `publications`/`connections` for optimistic concurrency (`If-Match`).

## Lifecycle fields

| Purpose | Field(s) |
| --- | --- |
| Recovery after crash | `tasks.state`, `executions.state`, `status_timestamp`; worker re-polls non-terminal executions older than `RECOVERY_AFTER` |
| Retention | `tasks.expires_at` (`TASK_RETENTION_DAYS`), artifacts cascade; `executions` kept for attribution (`EXECUTION_RETENTION_DAYS`) |
| Revocation | `publications.disabled_at` → running tasks finish, new sends rejected; core space deletion → reconcile disables publication |
| Attribution / quotas | `executions.user_id`, `tasks.user_id`, counters derived by query, no content stored beyond `task_snapshot` (which excludes Unique-internal fields) |

## Task store

`PgTaskStore implements TaskStore` from `@a2a-js/sdk` (`save`, `load`, `list` with `ServerCallContext`): `context.user` → `(companyId, userId)`; `task_snapshot` is the protocol `Task` as served to clients, the mapping columns are ours.

## Worker jobs (pg-boss, same database)

| Job | Trigger | Idempotency key |
| --- | --- | --- |
| `outbound.poll` | remote without streaming, or stream dropped | `executionId` |
| `push.deliver` | task status change with configs | `taskId:statusTimestamp:configId` |
| `reconcile.publications` | schedule | singleton |
| `retention.expire` | schedule | singleton |
