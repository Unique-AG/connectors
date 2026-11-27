# Space Config MCP — Product Specification

## Purpose

Space Config MCP is an AI agent tool server (Model Context Protocol) that lets an AI agent
read and modify the configuration of the Unique AI space it is currently running in.

A *space* is a Unique AI workspace tied to a specific assistant setup — its model, behaviour,
access rules, and module configuration. This MCP exposes those controls as agent-callable tools
so that administrators can delegate space management to an AI agent rather than navigating the
admin portal manually.

---

## Scope boundary

**In scope — the calling space only.**
Every tool operates exclusively on the space the calling assistant belongs to. The space identity
is derived from the platform-injected request context (`unique.app/chat/assistant-id`), not from
any parameter the caller supplies. An agent cannot read or modify a different space.

**Exception — Magic Table cross-space reads.**
`get_magic_table_config` and `update_magic_table_config` accept an optional `target_space_id`
parameter. This lets a Conduct or command space configure a Magic Table space that has no chat
interface of its own. The parameter is validated: the target module must exist in the named space.

**Out of scope.**
- Creating or deleting spaces
- Arbitrary cross-space operations (beyond the Magic Table exception above)
- Company-level or platform-level configuration

---

## Permission model

| Category | What the tool can do | Requires |
|---|---|---|
| **Read** | Inspect space metadata, modules, access list, snapshots | Standard assistant access |
| **Write** | Change space name, description, model, settings | Admin access on the space |
| **Module write** | Change Conduct harness configuration | Admin access on the space |
| **Access management** | Grant or revoke user/group access | Admin access on the space |
| **Snapshot / history** | Capture, list, retrieve, revert, delete snapshots | Admin access on the space |

> **Safety guardrail — auto-snapshot before every write.**
> Every mutating tool (`update_space`, `update_conduct_config`, `update_module_config`,
> `add_space_access`, `delete_space_access`) automatically captures the current space
> configuration as a snapshot before applying any change. The snapshot is stored in the
> knowledge base and can be used to revert if the change produces unintended effects.
> The write proceeds even when the snapshot storage fails (best-effort).

> **Known limitation — snapshots do not include access entries.**
> A snapshot captures space metadata and module configuration. It does **not** capture the
> access list (users and groups). `revert_space` therefore cannot restore access after an
> `add_space_access` or `delete_space_access` call. Use `get_space_access` to record
> the access list before making access changes if restoration might be needed.

> **Known limitation — concurrent updates.**
> Two concurrent calls to `update_magic_table_config` (or `update_module_config`) may each
> read the same current config and then write, with the first write lost. This is a
> last-write-wins race. Avoid issuing parallel writes to the same module.

---

## Tools

### Space

| Tool | Read / Write | Description |
|---|---|---|
| `get_space` | Read | Full space config: metadata, modules, scope rules, access |
| `update_space` | Write | Change name, description, alert, model, pinning, settings |

### Modules

| Tool | Read / Write | Description |
|---|---|---|
| `list_modules` | Read | All modules attached to the space |
| `get_module` | Read | A single module with its full configuration dict |
| `get_conduct_config` | Read | Typed view of the SwappableIntelligence (Conduct) harness config |
| `update_conduct_config` | Write | Patch Conduct harness settings (strategy, model, effort, setup) |
| `update_module_config` | Write | Generic patch for any module's configuration dict |

### Access

| Tool | Read / Write | Description |
|---|---|---|
| `get_space_access` | Read | Current access entries (users and groups) on the space |
| `add_space_access` | Write | Grant access to users or groups |
| `delete_space_access` | Write | Revoke access entries by ID |

### Snapshots

| Tool | Read / Write | Description |
|---|---|---|
| `snapshot_space` | Write | Capture the current full config as a named snapshot |
| `list_snapshots` | Read | List all stored snapshots for the space, newest first |
| `get_snapshot` | Read | Retrieve the full config JSON for a specific snapshot |
| `revert_space` | Write | Apply a snapshot's config back to the live space |
| `delete_snapshots` | Write | Delete all snapshots for the space (irreversible) |
| `export_space_config` | Read | Return the current config as a JSON string (no KB write) |
| `import_space_config` | Write | Apply a JSON config string to the space |

---

## Gherkin flows

### 1 — Inspect the current configuration

```gherkin
Feature: Read space configuration

  Scenario: Agent reviews what the space is currently set to
    Given the agent is running inside a Unique AI space
    When the agent calls get_space
    Then the agent receives the full space object including name, model, modules, and access

  Scenario: Agent checks the Conduct harness settings
    Given the space uses the SwappableIntelligence (Conduct) module
    When the agent calls get_conduct_config
    Then the agent receives the module ID and a typed configuration
     And the configuration includes the active strategy, model, effort, and setup options
```

### 2 — Update space metadata

```gherkin
Feature: Update space metadata

  Scenario: Agent renames the space and updates its description
    Given the agent has admin access on the calling space
    When the agent calls update_space with a new name and explanation
    Then the platform records a pre-update snapshot of the current config
     And the space name and description are updated
     And the agent receives the updated space object

  Scenario: Agent changes the language model
    Given the space is currently using gpt-4o
    When the agent calls update_space with language_model="gpt-4.1"
    Then the platform records a pre-update snapshot
     And the space switches to gpt-4.1 for all new conversations
```

### 3 — Update the Conduct harness

```gherkin
Feature: Manage Conduct harness configuration

  Scenario: Agent increases the max agent turns
    Given the Conduct harness is configured with claude_code strategy
    When the agent calls update_conduct_config with max_turns=50
    Then the platform records a pre-update snapshot
     And claude.maxTurns is updated to 50 in the module configuration
     And all other configuration keys remain unchanged

  Scenario: Agent adds custom instructions to the system prompt
    Given the space has an existing system prompt setup
    When the agent calls update_conduct_config with custom_instructions="Always reply in German."
    Then the platform records a pre-update snapshot
     And setup.customInstructions is set to the new value
     And existing setup keys (e.g. enableCodeExecution) are preserved
```

### 4 — Manage access

```gherkin
Feature: Manage space access

  Scenario: Agent grants USE access to a user
    Given the agent has admin access on the calling space
    When the agent calls add_space_access with entityId, entityType=USER, type=USE
    Then the platform records a pre-update snapshot of the current access state
     And the user is added to the space access list with USE permission

  Scenario: Agent revokes access
    Given the space has an access entry with a known ID
    When the agent calls delete_space_access with that access ID
    Then the platform records a pre-update snapshot
     And the entry is removed from the access list
```

### 5 — Snapshot and revert

```gherkin
Feature: Snapshot and rollback

  Scenario: Agent takes a manual checkpoint before making changes
    Given the agent is about to apply several configuration changes
    When the agent calls snapshot_space with label="before-migration"
    Then a full config snapshot is stored in the knowledge base
     And the agent receives the snapshot ID and label

  Scenario: Agent lists available snapshots
    When the agent calls list_snapshots
    Then the agent receives a list of snapshots sorted newest-first
     And each entry includes a snapshot_id, label, and captured_at timestamp

  Scenario: Agent reverts to a previous state
    Given the agent has a snapshot_id from list_snapshots
    When the agent calls revert_space with that snapshot_id
    Then the platform first captures a pre-revert snapshot of the current state
     And space metadata is restored from the chosen snapshot
     And all module configurations are restored from the chosen snapshot
     And the agent receives both the reverted-to ID and the safety snapshot ID

  Scenario: Agent cleans up snapshot history
    Given the space has accumulated many snapshots
    When the agent calls delete_snapshots
    Then all snapshot data is permanently removed from the knowledge base
```

### 6 — Export and import (config portability)

```gherkin
Feature: Export and import space configuration

  Scenario: Agent exports config for auditing or migration
    When the agent calls export_space_config
    Then the agent receives the full current space config as a JSON string
     And no data is written to the knowledge base

  Scenario: Agent imports a config from another space
    Given the agent has a valid config JSON string from another space
    When the agent calls import_space_config with that JSON
    Then the platform first captures a pre-import snapshot of the current state
     And space metadata and module configurations are applied from the JSON
     And the agent receives confirmation and the safety snapshot ID
```

---

## What this MCP does NOT do

| Action | Why it is excluded |
|---|---|
| Read or modify other spaces | Space ID is locked to the calling assistant; Magic Table cross-space is the sole exception |
| Restore access entries via revert | Snapshots capture config and modules, not the access list |
| Create or delete spaces | Out of scope; requires platform-level admin, not tool-level calls |
| Manage company-level settings | No company-scoped write tools |
| Delete individual snapshot versions | The KB API does not support per-version deletion; only full history deletion is exposed |
| Bypass the auto-snapshot | Every mutating tool always attempts a snapshot first |

---

## Server info

| Property | Value |
|---|---|
| **MCP protocol revision** | `2025-06-18` (FastMCP 4.1.4) |
| **Transport** | Streamable HTTP (`https://`) |
| **Auth** | Zitadel OIDC — authorization code + PKCE S256, public client, dynamic client registration |
| **Tested client** | Unique AI platform (node-chat SDK `@modelcontextprotocol/sdk` 1.3x, up to `2025-11-25`) |
| **Tool count** | 24 |
| **Definition size** | ~32 KB |

### Security model

Space identity is derived from `unique.app/chat/assistant-id` injected by the Unique platform in
`_meta`. Before any tool proceeds, the server calls `get_space` to verify the space exists under
the authenticated company (using the company-scoped API key). This guards against a forged
`_meta` value redirecting a tool at a different space within the same company.

The company boundary is enforced by the API key: `SPACE_CONFIG_MCP_UNIQUE_API_KEY` is scoped to
one company, so cross-company access is not possible regardless of `_meta` values.

> **High-privilege operations.**
> `update_conduct_config` accepts `system_prompt_override` and `agent_md_instructions` — fields
> that fully replace the agent's system prompt or inject AGENT.md content. These are the
> highest-privilege operations this MCP exposes. The existing gate (JWT + verified space
> ownership) is the correct authorization boundary today. If Unique adds per-action permission
> tiers in future, these fields are the first candidates for a MANAGE-level requirement.
>
> `update_module_config` is an untyped escape hatch that bypasses the validated paths of
> `update_conduct_config`, `update_translator_config`, and `update_magic_table_config`. Use it
> only for modules that have no dedicated tool. For the three modules above, prefer their typed
> tools to avoid unintentional overwrites of sensitive keys.

---

## Open questions / potential extensions

- **Granular snapshot deletion**: delete a single version rather than all history (depends on KB API support).
- **Diff view**: show what changed between two snapshots.
- **Scheduled snapshots**: capture config on a schedule without an agent trigger.
- **Read-only mode**: an optional flag that makes all write tools return a dry-run diff instead of applying changes.
- **Audit log**: expose a log of which tool called what, by which user, and when.
