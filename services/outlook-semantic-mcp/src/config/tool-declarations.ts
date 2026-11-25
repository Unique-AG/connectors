export type ToolFeature = 'uniqueMode' | 'debugMode' | 'calendar';

export interface ToolDeclaration {
  readonly requires: readonly ToolFeature[];
}

export const FEATURE_SETTINGS: Record<ToolFeature, string> = {
  uniqueMode: 'MCP_BACKEND=microsoft_graph_and_unique_api',
  debugMode: 'MCP_DEBUG_MODE=enabled',
  calendar: 'CALENDAR_INTEGRATION=enabled',
};

// Order is the registration order, which is the order clients list the tools in.
const declarations = {
  list_mailboxes_and_directories: { requires: [] },
  list_categories: { requires: [] },
  draft_email: { requires: [] },
  update_draft_email: { requires: [] },
  add_attachments_to_draft_email: { requires: [] },
  remove_attachments_from_draft_email: { requires: [] },
  lookup_contacts: { requires: [] },
  search_emails: { requires: [] },
  fetch_next_search_pages: { requires: [] },
  open_email: { requires: [] },
  sync_progress: { requires: ['uniqueMode'] },
  verify_inbox_connection: { requires: ['uniqueMode'] },
  delete_inbox_data: { requires: ['uniqueMode'] },
  reconnect_inbox: { requires: ['uniqueMode'] },
  run_full_sync: { requires: ['uniqueMode', 'debugMode'] },
  restart_full_sync: { requires: ['uniqueMode', 'debugMode'] },
  pause_full_sync: { requires: ['uniqueMode', 'debugMode'] },
  resume_full_sync: { requires: ['uniqueMode', 'debugMode'] },
  admin_ops: { requires: ['uniqueMode', 'debugMode'] },
  list_calendars: { requires: ['calendar'] },
  search_calendar_events: { requires: ['calendar'] },
  check_availability: { requires: ['calendar'] },
  suggest_meeting_times: { requires: ['calendar'] },
  respond_to_invite: { requires: ['calendar'] },
  create_event: { requires: ['calendar'] },
  update_event: { requires: ['calendar'] },
  cancel_event: { requires: ['calendar'] },
} as const satisfies Record<string, ToolDeclaration>;

export type ToolName = keyof typeof declarations;

export const TOOL_DECLARATIONS: Readonly<Record<ToolName, ToolDeclaration>> = declarations;

export const TOOL_NAMES = Object.keys(TOOL_DECLARATIONS) as ToolName[];

export const isToolName = (name: string): name is ToolName =>
  Object.hasOwn(TOOL_DECLARATIONS, name);
