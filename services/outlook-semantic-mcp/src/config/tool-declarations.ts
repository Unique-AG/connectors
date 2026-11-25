export type ToolGroup = 'mail' | 'calendar' | 'sync' | 'debug';

export type ToolFeature = 'uniqueMode' | 'debugMode';

export const GRAPH_PERMISSIONS = [
  'User.Read',
  'User.Read.All',
  'Mail.Read',
  'Mail.ReadWrite',
  'Mail.Read.Shared',
  'Mail.ReadWrite.Shared',
  'MailboxSettings.Read',
  'People.Read',
  'Calendars.ReadWrite.Shared',
] as const;

export type GraphPermission = (typeof GRAPH_PERMISSIONS)[number];

export interface ToolDeclaration {
  readonly group: ToolGroup;
  readonly permissions: readonly GraphPermission[];
}

export const GROUP_REQUIRES: Record<ToolGroup, readonly ToolFeature[]> = {
  mail: [],
  calendar: [],
  sync: ['uniqueMode'],
  debug: ['uniqueMode', 'debugMode'],
};

export const FEATURE_SETTINGS: Record<ToolFeature, string> = {
  uniqueMode: 'MCP_BACKEND=microsoft_graph_and_unique_api',
  debugMode: 'MCP_DEBUG_MODE=enabled',
};

// Order is the registration order, which is the order clients list the tools in. Permissions are
// everything the tool's Graph calls need, the shared time-zone lookup (MailboxSettings.Read) included.
const declarations = {
  list_mailboxes_and_directories: { group: 'mail', permissions: ['Mail.Read'] },
  list_categories: { group: 'mail', permissions: ['MailboxSettings.Read'] },
  draft_email: { group: 'mail', permissions: ['Mail.ReadWrite'] },
  update_draft_email: { group: 'mail', permissions: ['Mail.ReadWrite'] },
  add_attachments_to_draft_email: { group: 'mail', permissions: ['Mail.ReadWrite'] },
  remove_attachments_from_draft_email: { group: 'mail', permissions: ['Mail.ReadWrite'] },
  lookup_contacts: { group: 'mail', permissions: ['People.Read', 'Mail.Read'] },
  search_emails: { group: 'mail', permissions: ['Mail.Read', 'MailboxSettings.Read'] },
  fetch_next_search_pages: { group: 'mail', permissions: ['Mail.Read', 'MailboxSettings.Read'] },
  open_email: { group: 'mail', permissions: ['Mail.Read', 'MailboxSettings.Read'] },
  sync_progress: { group: 'sync', permissions: [] },
  verify_inbox_connection: { group: 'sync', permissions: [] },
  delete_inbox_data: { group: 'sync', permissions: ['Mail.Read'] },
  reconnect_inbox: { group: 'sync', permissions: ['Mail.Read'] },
  run_full_sync: { group: 'debug', permissions: ['Mail.Read'] },
  restart_full_sync: { group: 'debug', permissions: ['Mail.Read'] },
  pause_full_sync: { group: 'debug', permissions: [] },
  resume_full_sync: { group: 'debug', permissions: ['Mail.Read'] },
  admin_ops: { group: 'debug', permissions: ['Mail.Read'] },
  list_calendars: { group: 'calendar', permissions: ['Calendars.ReadWrite.Shared'] },
  search_calendar_events: {
    group: 'calendar',
    permissions: ['Calendars.ReadWrite.Shared', 'MailboxSettings.Read'],
  },
  check_availability: {
    group: 'calendar',
    permissions: ['Calendars.ReadWrite.Shared', 'MailboxSettings.Read'],
  },
  suggest_meeting_times: {
    group: 'calendar',
    permissions: ['Calendars.ReadWrite.Shared', 'MailboxSettings.Read'],
  },
  respond_to_invite: { group: 'calendar', permissions: ['Calendars.ReadWrite.Shared'] },
  create_event: {
    group: 'calendar',
    permissions: ['Calendars.ReadWrite.Shared', 'MailboxSettings.Read'],
  },
  update_event: {
    group: 'calendar',
    permissions: ['Calendars.ReadWrite.Shared', 'MailboxSettings.Read'],
  },
  cancel_event: {
    group: 'calendar',
    permissions: ['Calendars.ReadWrite.Shared', 'MailboxSettings.Read'],
  },
} as const satisfies Record<string, ToolDeclaration>;

export type ToolName = keyof typeof declarations;

export const TOOL_DECLARATIONS: Readonly<Record<ToolName, ToolDeclaration>> = declarations;

export const TOOL_NAMES = Object.keys(TOOL_DECLARATIONS) as ToolName[];

export const isToolName = (name: string): name is ToolName =>
  Object.hasOwn(TOOL_DECLARATIONS, name);

export const toolsInGroup = (group: ToolGroup): ToolName[] =>
  TOOL_NAMES.filter((name) => TOOL_DECLARATIONS[name].group === group);
