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

const tools = (...names: string[]) => JSON.stringify(names);

describe(loadFeaturesConfig.name, () => {
  it('reads the mode and the listed tools', () => {
    const config = load({ MCP_TOOLS: tools('search_emails', 'sync_progress') });

    expect(config.mode).toBe(McpBackendType.MicrosoftGraphAndUniqueApi);
    expect([...config.tools]).toEqual(['search_emails', 'sync_progress']);
  });

  it('keeps the listed tools in registration order', () => {
    const config = load({ MCP_TOOLS: tools('open_email', 'search_emails') });

    expect([...config.tools]).toEqual(['search_emails', 'open_email']);
  });

  it('turns calendar on only when a calendar tool is listed', () => {
    expect(load({ MCP_TOOLS: tools('search_emails', 'list_calendars') }).calendar).toBe(true);
    expect(load({ MCP_TOOLS: tools('search_emails') }).calendar).toBe(false);
  });

  describe('Unique', () => {
    it('is needed in Unique mode with Unique attachments off', () => {
      const config = load({ UNIQUE_ATTACHMENTS: 'disabled', MCP_TOOLS: tools('search_emails') });

      expect(config.uniqueAttachments).toBe(false);
      expect(config.uniqueNeeded).toBe(true);
    });

    it('is needed in microsoft_graph mode while Unique attachments are on by default', () => {
      const config = load({ MCP_BACKEND: 'microsoft_graph', MCP_TOOLS: tools('search_emails') });

      expect(config.uniqueAttachments).toBe(true);
      expect(config.uniqueNeeded).toBe(true);
    });

    it('is not needed in microsoft_graph mode with Unique attachments off', () => {
      const config = load({ ...READ_ONLY_ENV, UNIQUE_ATTACHMENTS: 'disabled' });

      expect(config.uniqueNeeded).toBe(false);
    });

    it('throws naming UNIQUE_ATTACHMENTS when it is not enabled or disabled', () => {
      expect(() => load({ UNIQUE_ATTACHMENTS: 'off', MCP_TOOLS: tools('search_emails') })).toThrow(
        /UNIQUE_ATTACHMENTS: /,
      );
    });
  });

  it('throws naming MCP_BACKEND when it is unset', () => {
    expect(() =>
      loadFeaturesConfig({ DELEGATED_ACCESS_SCAN: 'disabled', MCP_TOOLS: tools('search_emails') }),
    ).toThrow(/MCP_BACKEND: /);
  });

  it('throws naming DELEGATED_ACCESS_SCAN when its value is unknown', () => {
    expect(() => load({ DELEGATED_ACCESS_SCAN: 'disable' })).toThrow(/DELEGATED_ACCESS_SCAN: /);
  });

  describe('MCP_TOOLS', () => {
    it.each([
      ['unset', undefined],
      ['empty', ''],
      ['a comma-separated list', 'search_emails,open_email'],
      ['a JSON object', '{"tools":["search_emails"]}'],
    ])('throws asking for a JSON array of tool names when it is %s', (_case, value) => {
      expect(() => load({ MCP_TOOLS: value })).toThrow(
        'MCP_TOOLS: required, a JSON array of tool names',
      );
    });

    it('throws when the list is empty', () => {
      expect(() => load({ MCP_TOOLS: '[]' })).toThrow('MCP_TOOLS: lists no tool');
    });

    it('throws naming an unknown tool', () => {
      expect(() => load({ MCP_TOOLS: tools('create_draft_email') })).toThrow(
        'MCP_TOOLS: unknown tool "create_draft_email"',
      );
    });

    it('throws naming a Unique-only tool and MCP_BACKEND in microsoft_graph mode', () => {
      expect(() =>
        load({ MCP_BACKEND: 'microsoft_graph', MCP_TOOLS: tools('sync_progress') }),
      ).toThrow('MCP_TOOLS: "sync_progress" needs MCP_BACKEND=microsoft_graph_and_unique_api');
    });

    it('throws naming a debug tool and MCP_DEBUG_MODE with debug off', () => {
      expect(() => load({ MCP_DEBUG_MODE: 'disabled', MCP_TOOLS: tools('run_full_sync') })).toThrow(
        'MCP_TOOLS: "run_full_sync" needs MCP_DEBUG_MODE=enabled',
      );
    });

    it('accepts a debug tool with debug on in Unique mode', () => {
      const config = load({ MCP_DEBUG_MODE: 'enabled', MCP_TOOLS: tools('run_full_sync') });

      expect([...config.tools]).toEqual(['run_full_sync']);
    });

    it('names every missing setting of a tool', () => {
      expect(() => load({ MCP_BACKEND: 'microsoft_graph', MCP_TOOLS: tools('admin_ops') })).toThrow(
        'MCP_TOOLS: "admin_ops" needs MCP_BACKEND=microsoft_graph_and_unique_api and MCP_DEBUG_MODE=enabled',
      );
    });

    it('accepts the calendar tools in either mode', () => {
      const config = load({ MCP_BACKEND: 'microsoft_graph', MCP_TOOLS: tools('cancel_event') });

      expect([...config.tools]).toEqual(['cancel_event']);
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
    vi.stubEnv('MCP_TOOLS', tools('sync_progress'));

    await expect(featuresConfig()).rejects.toThrow(/"sync_progress"/);
  });
});
