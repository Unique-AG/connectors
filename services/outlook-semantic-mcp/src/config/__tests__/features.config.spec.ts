import { afterEach, describe, expect, it, vi } from 'vitest';
import { featuresConfig, loadFeaturesConfig } from '../features.config';
import { McpBackendType } from '../mcp-backend-type.config';

const READ_ONLY_ENV = {
  MCP_BACKEND: 'microsoft_graph',
  DELEGATED_ACCESS_SCAN: 'disabled',
  MCP_TOOLS: JSON.stringify([
    'search_emails',
    'fetch_next_search_pages',
    'open_email',
    'list_mailboxes_and_directories',
    'list_categories',
    'lookup_contacts',
  ]),
};

const load = (env: NodeJS.ProcessEnv) =>
  loadFeaturesConfig({
    MCP_BACKEND: 'microsoft_graph_and_unique_api',
    DELEGATED_ACCESS_SCAN: 'full_access_only',
    ...env,
  });

describe(loadFeaturesConfig.name, () => {
  it('reads the mode, calendar, shared mailboxes and debug mode from today’s variables', () => {
    const config = load({ CALENDAR_INTEGRATION: 'enabled', MCP_DEBUG_MODE: 'enabled' });

    expect(config).toMatchObject({
      mode: McpBackendType.MicrosoftGraphAndUniqueApi,
      calendar: true,
      sharedMailboxes: true,
      debug: true,
    });
  });

  it('turns shared mailboxes off only when DELEGATED_ACCESS_SCAN is disabled', () => {
    expect(load({ DELEGATED_ACCESS_SCAN: 'disabled' }).sharedMailboxes).toBe(false);
    expect(load({ DELEGATED_ACCESS_SCAN: 'granular_access' }).sharedMailboxes).toBe(true);
  });

  it('throws naming MCP_BACKEND when it is unset', () => {
    expect(() => loadFeaturesConfig({ DELEGATED_ACCESS_SCAN: 'disabled' })).toThrow(/MCP_BACKEND/);
  });

  it('throws naming DELEGATED_ACCESS_SCAN when it is unset', () => {
    expect(() => loadFeaturesConfig({ MCP_BACKEND: 'microsoft_graph' })).toThrow(
      /DELEGATED_ACCESS_SCAN/,
    );
  });

  describe('MCP_TOOLS', () => {
    it('keeps the listed tools in registration order', () => {
      const config = load({
        MCP_BACKEND: 'microsoft_graph',
        MCP_TOOLS: JSON.stringify(['open_email', 'search_emails']),
      });

      expect([...config.tools]).toEqual(['search_emails', 'open_email']);
    });

    it('throws naming an unknown tool', () => {
      expect(() => load({ MCP_TOOLS: JSON.stringify(['create_draft_email']) })).toThrow(
        'MCP_TOOLS: unknown tool "create_draft_email"',
      );
    });

    it('throws naming a Unique-only tool and MCP_BACKEND in microsoft_graph mode', () => {
      expect(() =>
        load({ MCP_BACKEND: 'microsoft_graph', MCP_TOOLS: JSON.stringify(['sync_progress']) }),
      ).toThrow('MCP_TOOLS: "sync_progress" needs MCP_BACKEND=microsoft_graph_and_unique_api');
    });

    it('throws naming a debug tool and MCP_DEBUG_MODE with debug off', () => {
      expect(() =>
        load({ MCP_DEBUG_MODE: 'disabled', MCP_TOOLS: JSON.stringify(['run_full_sync']) }),
      ).toThrow('MCP_TOOLS: "run_full_sync" needs MCP_DEBUG_MODE=enabled');
    });

    it('names every missing setting of a tool', () => {
      expect(() =>
        load({ MCP_BACKEND: 'microsoft_graph', MCP_TOOLS: JSON.stringify(['admin_ops']) }),
      ).toThrow(
        'MCP_TOOLS: "admin_ops" needs MCP_BACKEND=microsoft_graph_and_unique_api and MCP_DEBUG_MODE=enabled',
      );
    });

    it('throws naming a calendar tool and CALENDAR_INTEGRATION with calendar off', () => {
      expect(() =>
        load({ CALENDAR_INTEGRATION: 'disabled', MCP_TOOLS: JSON.stringify(['list_calendars']) }),
      ).toThrow('MCP_TOOLS: "list_calendars" needs CALENDAR_INTEGRATION=enabled');
    });

    it.each([
      ['an empty list', '[]'],
      ['a comma-separated list', 'search_emails,open_email'],
    ])('throws naming MCP_TOOLS for %s', (_case, value) => {
      expect(() => load({ MCP_TOOLS: value })).toThrow(/MCP_TOOLS: /);
    });
  });
});

describe('featuresConfig', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('parses the environment the same way as loadFeaturesConfig', async () => {
    for (const [key, value] of Object.entries(READ_ONLY_ENV)) {
      vi.stubEnv(key, value);
    }

    expect(await featuresConfig()).toEqual(loadFeaturesConfig(READ_ONLY_ENV));
  });

  it('fails naming the tool in MCP_TOOLS', async () => {
    vi.stubEnv('MCP_BACKEND', 'microsoft_graph');
    vi.stubEnv('DELEGATED_ACCESS_SCAN', 'disabled');
    vi.stubEnv('MCP_TOOLS', JSON.stringify(['sync_progress']));

    await expect(featuresConfig()).rejects.toThrow(/"sync_progress"/);
  });
});
