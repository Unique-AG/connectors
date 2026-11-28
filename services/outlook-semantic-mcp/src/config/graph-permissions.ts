import { McpBackendType } from './mcp-backend-type.config';
import { type GraphPermission, TOOL_DECLARATIONS, type ToolName } from './tool-declarations';

// The profile is read from GET /me, so `profile` and `email` only shape the ID token, which is not read.
const PROFILE_SCOPES = ['profile', 'email'] as const;

// Sign-in reads GET /me, and the folder sync reads every deployment's mail folders whatever the tools.
export const BASE_PERMISSIONS: readonly GraphPermission[] = ['User.Read', 'Mail.Read'];

// Full sync, live catch-up and the mail subscription.
export const UNIQUE_MODE_PERMISSIONS: readonly GraphPermission[] = ['Mail.Read'];

// With shared mailboxes on, each own mail permission brings its `.Shared` counterpart.
export const SHARED_COUNTERPARTS: Partial<Record<GraphPermission, GraphPermission>> = {
  'Mail.Read': 'Mail.Read.Shared',
  'Mail.ReadWrite': 'Mail.ReadWrite.Shared',
};

export const SHARED_MAILBOX_PERMISSIONS: readonly GraphPermission[] = ['User.Read.All'];

// A write permission covers its read permission, so the read one is not requested.
export const REPLACES: Partial<Record<GraphPermission, GraphPermission>> = {
  'Mail.ReadWrite': 'Mail.Read',
  'Mail.ReadWrite.Shared': 'Mail.Read.Shared',
};

interface PermissionSelection {
  readonly mode: McpBackendType;
  readonly tools: ReadonlySet<ToolName>;
  readonly sharedMailboxes: boolean;
  readonly offlineAccess: boolean;
  readonly profileScopes: boolean;
}

export function resolveGraphPermissions(
  selection: Pick<PermissionSelection, 'mode' | 'tools' | 'sharedMailboxes'>,
): GraphPermission[] {
  const own = [
    ...BASE_PERMISSIONS,
    ...(selection.mode === McpBackendType.MicrosoftGraphAndUniqueApi
      ? UNIQUE_MODE_PERMISSIONS
      : []),
    ...[...selection.tools].flatMap((tool) => TOOL_DECLARATIONS[tool].permissions),
  ];
  const shared = selection.sharedMailboxes
    ? [...SHARED_MAILBOX_PERMISSIONS, ...own.flatMap((p) => SHARED_COUNTERPARTS[p] ?? [])]
    : [];
  const requested = new Set([...own, ...shared]);
  const replaced = new Set([...requested].flatMap((p) => REPLACES[p] ?? []));
  return [...requested].filter((p) => !replaced.has(p)).sort();
}

export function resolveScopes(selection: PermissionSelection): string[] {
  return [
    'openid',
    ...(selection.profileScopes ? PROFILE_SCOPES : []),
    ...(selection.offlineAccess ? ['offline_access'] : []),
    ...resolveGraphPermissions(selection),
  ].sort();
}
