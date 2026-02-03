# Design: Top Folder Permissions Aggregation

**Ticket:** UN-15850

## Problem

The SharePoint connector currently assigns "Root Group" (All Company) access to site and library scopes by default. This means everyone can see every site and library name that gets synced, regardless of whether they have access to any content within.

If site and library names are considered sensitive, this exposes information users shouldn't see.

## Solution

### Overview

Replace the "Root Group" default with aggregated group permissions from files and folders within each scope. Users will only see site/library names if they belong to a group that has access to at least one file or folder within that scope.

Key decisions:
- Only **group** permissions are aggregated (not individual users)
- Aggregation includes permissions from both files and directories
- Site scope gets all groups from the entire site
- Library scope gets groups from that library only

### Architecture

Split `SyncSharepointFolderPermissionsToUniqueCommand` into separate queries and a command:

```
Queries (data gathering, no side effects):
├── GetRegularFolderPermissionsQuery      - Gets SharePoint permissions for level 2+ folders
└── GetTopFolderPermissionsQuery          - Aggregates group permissions for site/library scopes

Command (mapping + syncing):
└── SyncFolderPermissionsToUniqueCommand  - Maps to Unique entities and syncs
```

**Data flow in `PermissionsSyncService`:**

```typescript
// 1. Get permissions for regular folders (level 2+)
const regularFolderPermissions = await this.getRegularFolderPermissionsQuery.run({
  directories: sharePoint.directories,
  permissionsMap,
  rootPath: context.rootPath,
});

// 2. Get aggregated permissions for top folders (site + libraries)
const topFolderPermissions = await this.getTopFolderPermissionsQuery.run({
  items: sharePoint.items,
  directories: sharePoint.directories,
  permissionsMap,
  rootPath: context.rootPath,
});

// 3. Merge and sync all folder permissions
await this.syncFolderPermissionsToUniqueCommand.run({
  context,
  sharePoint: {
    folderPermissions: new Map([...regularFolderPermissions, ...topFolderPermissions]),
  },
  unique: {
    folders: unique.folders,
    groupsMap: updatedUniqueGroupsMap,
    usersMap: uniqueUsersMap,
  },
});
```

**Path hierarchy:**

| Level | Example | Permission Source |
|-------|---------|-------------------|
| 0 (Site) | `/RootScope` | Aggregated groups from all files + dirs |
| 1 (Library) | `/RootScope/Documents` | Aggregated groups from library's files + dirs |
| 2+ (Folder) | `/RootScope/Documents/Contracts` | Direct SharePoint directory permissions |

**Aggregation example:**

```
Site: /RootScope
├── Library1: /RootScope/Documents
│   ├── Folder: /RootScope/Documents/Contracts (has GroupA)
│   │   └── File: contract.pdf (has GroupA, GroupB, UserX)
│   └── File: readme.txt (has GroupC)
└── Library2: /RootScope/SharedDocs
    └── File: report.xlsx (has GroupD)

Aggregated permissions:
- Site scope (/RootScope): GroupA, GroupB, GroupC, GroupD
- Library1 (/RootScope/Documents): GroupA, GroupB, GroupC
- Library2 (/RootScope/SharedDocs): GroupD
```

### Error Handling

- Missing directory in permissionsMap: Log warning, skip folder
- No files under top folder: Return empty permissions (scope not visible to anyone)
- User/group not found in Unique: Filter out, log debug
- Service user: Never remove service user access

## Testing Strategy

Unit tests for each component:

**`GetTopFolderPermissionsQuery`:**
- Aggregates groups from files under site scope
- Aggregates groups from directories under site scope
- Filters out user permissions
- Library scope only includes its descendants
- Empty site returns empty permissions

**`GetRegularFolderPermissionsQuery`:**
- Returns directory permissions for level 2+ folders only
- Handles missing permissions gracefully

**`SyncFolderPermissionsToUniqueCommand`:**
- Maps memberships to scope accesses correctly
- Preserves service user access
- Handles combined input from both queries

## Out of Scope

- Fetching actual site/library permissions from SharePoint API
- Per-drive permissions API investigation
- Changing file-level permission sync behavior
- Special handling for SharePoint "Everyone" groups

## Tasks

1. **Create `GetRegularFolderPermissionsQuery`** - Extract existing directory permissions lookup logic into a separate query that returns `Map<folderPath, Membership[]>` for folders at level 2+.

2. **Create `GetTopFolderPermissionsQuery`** - New query that aggregates group permissions from all files and directories under site and library scopes, filtering out user permissions.

3. **Refactor `SyncFolderPermissionsToUniqueCommand`** - Simplify to accept pre-gathered permissions map, handle mapping and syncing. Remove `isTopFolder` / Root Group logic.

4. **Update `PermissionsSyncService`** - Orchestrate the new queries and pass combined results to the command.

5. **Add unit tests** - Cover the new queries and refactored command.

6. **Remove Root Group usage** - Clean up Root Group references in folder permissions sync.
