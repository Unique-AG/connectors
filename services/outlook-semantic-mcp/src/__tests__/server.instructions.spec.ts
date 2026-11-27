import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildServerInstructions } from '../server.instructions';

const CALENDAR_TOOL_NAMES = [
  'list_calendars',
  'search_calendar_events',
  'check_availability',
  'suggest_meeting_times',
  'respond_to_invite',
  'create_event',
  'update_event',
  'cancel_event',
];

describe(buildServerInstructions.name, () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('omits calendar instructions when no calendar tool is listed', () => {
    vi.stubEnv('MCP_TOOLS', JSON.stringify(['search_emails']));
    const instructions = buildServerInstructions();

    for (const name of CALENDAR_TOOL_NAMES) {
      expect(instructions).not.toContain(name);
    }
  });

  it('includes calendar instructions when a calendar tool is listed', () => {
    vi.stubEnv('MCP_TOOLS', JSON.stringify(['search_emails', 'list_calendars']));
    const instructions = buildServerInstructions();

    for (const name of CALENDAR_TOOL_NAMES) {
      expect(instructions).toContain(name);
    }
  });
});

describe('email search instructions', () => {
  const original = process.env.MCP_BACKEND;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.MCP_BACKEND;
    } else {
      process.env.MCP_BACKEND = original;
    }
  });

  it.each(['microsoft_graph', 'microsoft_graph_and_unique_api'])(
    'explains previews, open_email and cursor paging for the %s backend',
    (backend) => {
      process.env.MCP_BACKEND = backend;
      const instructions = buildServerInstructions();
      expect(instructions).toContain('open_email');
      expect(instructions).toContain('fetch_next_search_pages');
      expect(instructions).toContain('retryAfterSeconds');
    },
  );
});
