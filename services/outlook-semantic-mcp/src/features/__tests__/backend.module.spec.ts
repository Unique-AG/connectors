import { MCP_TOOL_METADATA_KEY } from '@unique-ag/mcp-server-module';
import type { DynamicModule, Type } from '@nestjs/common';
import { describe, expect, it } from 'vitest';
import { loadFeaturesConfig } from '~/config';
import { registerBackendModule, TOOL_CLASSES } from '../backend.module';
import { CalendarModule } from '../calendar/calendar.module';

// What main registers, in its registration order.
const MAIN_COMMON_TOOLS = [
  'list_mailboxes_and_directories',
  'list_categories',
  'draft_email',
  'update_draft_email',
  'add_attachments_to_draft_email',
  'remove_attachments_from_draft_email',
  'lookup_contacts',
  'search_emails',
  'fetch_next_search_pages',
  'open_email',
];
const MAIN_UNIQUE_TOOLS = [
  'sync_progress',
  'verify_inbox_connection',
  'delete_inbox_data',
  'reconnect_inbox',
];
const MAIN_DEBUG_TOOLS = [
  'run_full_sync',
  'restart_full_sync',
  'pause_full_sync',
  'resume_full_sync',
  'admin_ops',
];
const MAIN_CALENDAR_TOOLS = [
  'list_calendars',
  'search_calendar_events',
  'check_availability',
  'suggest_meeting_times',
  'respond_to_invite',
  'create_event',
  'update_event',
  'cancel_event',
];

const READ_ONLY_TOOLS = [
  'search_emails',
  'fetch_next_search_pages',
  'open_email',
  'list_mailboxes_and_directories',
  'list_categories',
  'lookup_contacts',
];

const toolNameOf = (toolClass: Type): string | undefined =>
  Object.getOwnPropertyNames(toolClass.prototype)
    .map((key) => Reflect.getMetadata(MCP_TOOL_METADATA_KEY, toolClass.prototype[key]))
    .find(Boolean)?.name;

const registeredToolNames = (module: DynamicModule) =>
  (module.providers ?? []).flatMap((provider) => {
    const name = typeof provider === 'function' ? toolNameOf(provider) : undefined;
    return name ? [name] : [];
  });

const register = (env: NodeJS.ProcessEnv) => registerBackendModule(loadFeaturesConfig(env));

describe(registerBackendModule.name, () => {
  it.each([
    [
      'microsoft_graph_and_unique_api',
      'calendar on, debug on',
      'enabled',
      [...MAIN_COMMON_TOOLS, ...MAIN_UNIQUE_TOOLS, ...MAIN_DEBUG_TOOLS, ...MAIN_CALENDAR_TOOLS],
    ],
    [
      'microsoft_graph_and_unique_api',
      'calendar on, debug off',
      'disabled',
      [...MAIN_COMMON_TOOLS, ...MAIN_UNIQUE_TOOLS, ...MAIN_CALENDAR_TOOLS],
    ],
    [
      'microsoft_graph_and_unique_api',
      'calendar off, debug on',
      'enabled',
      [...MAIN_COMMON_TOOLS, ...MAIN_UNIQUE_TOOLS, ...MAIN_DEBUG_TOOLS],
    ],
    [
      'microsoft_graph_and_unique_api',
      'calendar off, debug off',
      'disabled',
      [...MAIN_COMMON_TOOLS, ...MAIN_UNIQUE_TOOLS],
    ],
    [
      'microsoft_graph',
      'calendar on, debug on',
      'enabled',
      [...MAIN_COMMON_TOOLS, ...MAIN_CALENDAR_TOOLS],
    ],
    [
      'microsoft_graph',
      'calendar on, debug off',
      'disabled',
      [...MAIN_COMMON_TOOLS, ...MAIN_CALENDAR_TOOLS],
    ],
    ['microsoft_graph', 'calendar off, debug on', 'enabled', MAIN_COMMON_TOOLS],
    ['microsoft_graph', 'calendar off, debug off', 'disabled', MAIN_COMMON_TOOLS],
  ])(
    'registers what main registers for %s, %s, from the rewritten config',
    (backend, _shape, debug, mainTools) => {
      const module = register({
        MCP_BACKEND: backend,
        MCP_DEBUG_MODE: debug,
        MCP_TOOLS: JSON.stringify([...mainTools].reverse()),
      });

      expect(registeredToolNames(module)).toEqual(mainTools);
    },
  );

  it('registers exactly the read-only tools in microsoft_graph mode', () => {
    const module = register({
      MCP_BACKEND: 'microsoft_graph',
      MCP_TOOLS: JSON.stringify(READ_ONLY_TOOLS),
    });

    expect(registeredToolNames(module).sort()).toEqual([...READ_ONLY_TOOLS].sort());
  });

  it('imports the calendar module only when a calendar tool is listed', () => {
    const on = register({
      MCP_BACKEND: 'microsoft_graph',
      MCP_TOOLS: JSON.stringify(['search_emails', 'list_calendars']),
    });
    const off = register({
      MCP_BACKEND: 'microsoft_graph',
      MCP_TOOLS: JSON.stringify(['search_emails']),
    });

    expect(on.imports).toContain(CalendarModule);
    expect(off.imports).not.toContain(CalendarModule);
  });
});

describe('TOOL_CLASSES', () => {
  it.each(Object.entries(TOOL_CLASSES))(
    'maps %s to the class whose @Tool has that name',
    (name, toolClass) => {
      expect(toolNameOf(toolClass)).toBe(name);
    },
  );
});
