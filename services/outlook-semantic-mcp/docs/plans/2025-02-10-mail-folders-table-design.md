# Design: Mail Folders Sync Table

**Ticket:** UN-16561

## Problem

Microsoft Graph does not provide change notifications for folder-level operations (move, rename, delete). When a user reorganizes their Outlook folders, there is no event-driven way to detect this. To support email ingestion that maps Outlook folders to Unique scopes, we need a local database table that mirrors the Outlook folder tree and links each folder to its corresponding Unique scope.

## Solution

### Overview

Create a `mail_folders` Drizzle table that acts as the local mirror of a user's Outlook mail folder hierarchy. Each row links a Microsoft Graph mail folder (`microsoftId`) to a Unique organizational scope (`uniqueScopeId`), scoped per user via `userProfileId`. The table supports the full parent-child tree via a self-referencing foreign key on `parentId`.

This table is purely the schema definition -- no sync logic is included in this change.

### Architecture

**Table: `mail_folders`**

| Column         | Type        | Constraints                                                        |
|----------------|-------------|--------------------------------------------------------------------|
| `id`           | `varchar`   | PK, generated via `typeid('mail_folder')`                          |
| `displayName`  | `varchar`   | NOT NULL                                                           |
| `parentId`     | `varchar`   | Nullable, self-referencing FK → `mail_folders.id` (cascade delete) |
| `microsoftId`  | `varchar`   | NOT NULL                                                           |
| `uniqueScopeId`| `varchar`   | NOT NULL, unique                                                   |
| `isSystemFolder`| `boolean`  | NOT NULL, default `false`                                          |
| `debugData`    | `jsonb`     | Nullable                                                           |
| `userProfileId`| `varchar`   | NOT NULL, FK → `user_profiles.id` (cascade delete/update)          |
| `createdAt`    | `timestamp` | NOT NULL, default `now()`                                          |
| `updatedAt`    | `timestamp` | NOT NULL, default `now()`, auto-update                             |

**Uniqueness constraints:**
1. `unique(userProfileId, microsoftId)` -- one entry per Microsoft folder per user mailbox
2. `unique(uniqueScopeId)` -- each Unique scope maps to at most one folder

**Self-referencing FK on `parentId`:**
- `onDelete: 'cascade'` -- deleting a parent cascades to children (mirrors folder tree behavior)
- Nullable because root-level folders (Inbox, Sent Items, etc.) have no parent

**File location:** `src/drizzle/schema/mail-folder/mail-folders.table.ts`

### Error Handling

Not applicable -- this change is purely a schema definition. Error handling will be part of the sync logic in a future task.

### Testing Strategy

No tests needed for this change -- it's a Drizzle schema definition and migration. The generated SQL migration will be reviewed manually.

## Out of Scope

- Folder sync logic (periodic polling, on-email-ingest checks)
- Microsoft Graph `mailFolders` API integration
- Folder move/rename detection algorithms
- Any service or controller code

## Tasks

1. **Create `mail_folders` Drizzle table schema** -- Define the table in `src/drizzle/schema/mail-folder/mail-folders.table.ts` with all columns, constraints, relations, and type exports. Create the barrel `index.ts` and re-export from the schema root.
2. **Generate Drizzle migration** -- Run `drizzle-kit generate` to produce the SQL migration file and verify the generated SQL is correct.
