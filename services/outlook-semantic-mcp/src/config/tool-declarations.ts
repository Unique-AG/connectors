export type ToolGroup = 'mail' | 'calendar' | 'sync' | 'debug';

export type ToolFeature = 'uniqueMode' | 'debugMode';

export interface ToolDeclaration {
  readonly group: ToolGroup;
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

// Order is the registration order, which is the order clients list the tools in.
const declarations = {
  list_mailboxes_and_directories: { group: 'mail' },
  list_categories: { group: 'mail' },
  draft_email: { group: 'mail' },
  update_draft_email: { group: 'mail' },
  add_attachments_to_draft_email: { group: 'mail' },
  remove_attachments_from_draft_email: { group: 'mail' },
  lookup_contacts: { group: 'mail' },
  search_emails: { group: 'mail' },
  fetch_next_search_pages: { group: 'mail' },
  open_email: { group: 'mail' },
  sync_progress: { group: 'sync' },
  verify_inbox_connection: { group: 'sync' },
  delete_inbox_data: { group: 'sync' },
  reconnect_inbox: { group: 'sync' },
  run_full_sync: { group: 'debug' },
  restart_full_sync: { group: 'debug' },
  pause_full_sync: { group: 'debug' },
  resume_full_sync: { group: 'debug' },
  admin_ops: { group: 'debug' },
  list_calendars: { group: 'calendar' },
  search_calendar_events: { group: 'calendar' },
  check_availability: { group: 'calendar' },
  suggest_meeting_times: { group: 'calendar' },
  respond_to_invite: { group: 'calendar' },
  create_event: { group: 'calendar' },
  update_event: { group: 'calendar' },
  cancel_event: { group: 'calendar' },
} as const satisfies Record<string, ToolDeclaration>;

export type ToolName = keyof typeof declarations;

export const TOOL_DECLARATIONS: Readonly<Record<ToolName, ToolDeclaration>> = declarations;

export const TOOL_NAMES = Object.keys(TOOL_DECLARATIONS) as ToolName[];

export const isToolName = (name: string): name is ToolName =>
  Object.hasOwn(TOOL_DECLARATIONS, name);

export const toolsInGroup = (group: ToolGroup): ToolName[] =>
  TOOL_NAMES.filter((name) => TOOL_DECLARATIONS[name].group === group);
