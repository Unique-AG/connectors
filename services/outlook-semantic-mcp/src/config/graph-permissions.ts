import { type GraphPermission, TOOL_DECLARATIONS, type ToolName } from './tool-declarations';

const OPENID_SCOPES = ['openid', 'profile', 'email'] as const;

const BASE_PERMISSIONS: readonly GraphPermission[] = [
  'User.Read',
  'Mail.Read',
  'People.Read',
  'MailboxSettings.Read',
];

// With shared mailboxes on, each own mail permission brings its `.Shared` counterpart.
const SHARED_COUNTERPARTS: Partial<Record<GraphPermission, GraphPermission>> = {
  'Mail.Read': 'Mail.Read.Shared',
  'Mail.ReadWrite': 'Mail.ReadWrite.Shared',
};

const SHARED_MAILBOX_PERMISSIONS: readonly GraphPermission[] = ['User.Read.All'];

// A write permission covers its read permission, so the read one is not requested.
const REPLACES: Partial<Record<GraphPermission, GraphPermission>> = {
  'Mail.ReadWrite': 'Mail.Read',
  'Mail.ReadWrite.Shared': 'Mail.Read.Shared',
};

interface PermissionSelection {
  readonly tools: ReadonlySet<ToolName>;
  readonly sharedMailboxes: boolean;
  readonly additionalGraphPermissions: readonly GraphPermission[];
}

function resolveGraphPermissions(selection: PermissionSelection): GraphPermission[] {
  const own = [
    ...BASE_PERMISSIONS,
    ...[...selection.tools].flatMap((tool) => TOOL_DECLARATIONS[tool].permissions),
  ];
  const shared = selection.sharedMailboxes
    ? [...SHARED_MAILBOX_PERMISSIONS, ...own.flatMap((p) => SHARED_COUNTERPARTS[p] ?? [])]
    : [];
  const requested = new Set([...own, ...shared, ...selection.additionalGraphPermissions]);
  const replaced = new Set([...requested].flatMap((p) => REPLACES[p] ?? []));
  return [...requested].filter((p) => !replaced.has(p)).sort();
}

export function resolveScopes(selection: PermissionSelection): string[] {
  return [...OPENID_SCOPES, 'offline_access', ...resolveGraphPermissions(selection)].sort();
}
