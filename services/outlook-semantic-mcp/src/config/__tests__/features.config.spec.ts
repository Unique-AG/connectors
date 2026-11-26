import { afterEach, describe, expect, it, vi } from 'vitest';
import { featuresConfig, LegacySensitivity, loadFeaturesConfig } from '../features.config';
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

  describe('DIRECTORY_SYNC_MODE', () => {
    it('is scheduled by default', () => {
      expect(load({ MCP_TOOLS: tools('search_emails') }).directorySyncMode).toBe('scheduled');
    });

    it('reads on_demand with shared mailboxes off', () => {
      expect(load({ ...READ_ONLY_ENV, DIRECTORY_SYNC_MODE: 'on_demand' }).directorySyncMode).toBe(
        'on_demand',
      );
    });

    it('throws naming DIRECTORY_SYNC_MODE when on_demand is set with shared mailboxes on', () => {
      expect(() =>
        load({
          MCP_BACKEND: 'microsoft_graph',
          DIRECTORY_SYNC_MODE: 'on_demand',
          MCP_TOOLS: tools('search_emails'),
        }),
      ).toThrow(/DIRECTORY_SYNC_MODE: "on_demand" needs DELEGATED_ACCESS_SCAN=disabled/);
    });

    it('throws naming DIRECTORY_SYNC_MODE when on_demand is set in Unique mode', () => {
      expect(() =>
        load({
          DIRECTORY_SYNC_MODE: 'on_demand',
          DELEGATED_ACCESS_SCAN: 'disabled',
          MCP_TOOLS: tools('search_emails'),
        }),
      ).toThrow(/DIRECTORY_SYNC_MODE: "on_demand" needs MCP_BACKEND=microsoft_graph/);
    });

    it('throws naming DIRECTORY_SYNC_MODE on an unknown value', () => {
      expect(() => load({ ...READ_ONLY_ENV, DIRECTORY_SYNC_MODE: 'hourly' })).toThrow(
        /DIRECTORY_SYNC_MODE: /,
      );
    });
  });

  describe('MICROSOFT_OFFLINE_ACCESS', () => {
    const offline = { ...READ_ONLY_ENV, DIRECTORY_SYNC_MODE: 'on_demand' };

    it('is on by default', () => {
      expect(load({ MCP_TOOLS: tools('search_emails') }).offlineAccess).toBe(true);
    });

    it('reads disabled in the read-only deployment', () => {
      expect(load({ ...offline, MICROSOFT_OFFLINE_ACCESS: 'disabled' }).offlineAccess).toBe(false);
    });

    it.each([
      ['MCP_BACKEND=microsoft_graph', { MCP_BACKEND: 'microsoft_graph_and_unique_api' }],
      ['DIRECTORY_SYNC_MODE=on_demand', { DIRECTORY_SYNC_MODE: 'scheduled' }],
      ['DELEGATED_ACCESS_SCAN=disabled', { DELEGATED_ACCESS_SCAN: 'full_access_only' }],
    ])('throws naming MICROSOFT_OFFLINE_ACCESS when disabled without %s', (needed, change) => {
      expect(() => load({ ...offline, MICROSOFT_OFFLINE_ACCESS: 'disabled', ...change })).toThrow(
        `MICROSOFT_OFFLINE_ACCESS: "disabled" needs ${needed}`,
      );
    });

    it('throws naming MICROSOFT_OFFLINE_ACCESS when it is not enabled or disabled', () => {
      expect(() => load({ ...offline, MICROSOFT_OFFLINE_ACCESS: 'off' })).toThrow(
        /MICROSOFT_OFFLINE_ACCESS: /,
      );
    });
  });

  describe('MICROSOFT_PROFILE_SCOPES', () => {
    it('is on by default and reads disabled', () => {
      expect(load({ MCP_TOOLS: tools('search_emails') }).profileScopes).toBe(true);
      expect(
        load({ MCP_TOOLS: tools('search_emails'), MICROSOFT_PROFILE_SCOPES: 'disabled' })
          .profileScopes,
      ).toBe(false);
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

  describe('EXCLUDED_SENSITIVITY_LABELS and EXCLUDED_LEGACY_SENSITIVITY', () => {
    it('exclude nothing by default', () => {
      expect(load(READ_ONLY_ENV).sensitivityExclusions).toEqual({
        labels: new Set(),
        legacy: new Set(),
      });
    });

    it('read Purview labels trimmed and as written, and legacy flags', () => {
      const config = load({
        ...READ_ONLY_ENV,
        EXCLUDED_SENSITIVITY_LABELS: JSON.stringify([
          ' Highly Confidential ',
          '2D69AFBC-F32C-424F-83AD-75460ACD2AA1',
        ]),
        EXCLUDED_LEGACY_SENSITIVITY: JSON.stringify(['private', 'confidential']),
      });

      expect(config.sensitivityExclusions).toEqual({
        labels: new Set(['Highly Confidential', '2D69AFBC-F32C-424F-83AD-75460ACD2AA1']),
        legacy: new Set([LegacySensitivity.Private, LegacySensitivity.Confidential]),
      });
    });

    it.each([
      ['EXCLUDED_LEGACY_SENSITIVITY', JSON.stringify(['secret'])],
      ['EXCLUDED_LEGACY_SENSITIVITY', JSON.stringify(['normal'])],
      ['EXCLUDED_SENSITIVITY_LABELS', JSON.stringify(['  '])],
      ['EXCLUDED_SENSITIVITY_LABELS', 'Confidential,Secret'],
    ])('throw naming %s for %s', (key, value) => {
      expect(() => load({ ...READ_ONLY_ENV, [key]: value })).toThrow(new RegExp(`${key}: `));
    });

    it.each([
      ['EXCLUDED_SENSITIVITY_LABELS', JSON.stringify(['Confidential'])],
      ['EXCLUDED_LEGACY_SENSITIVITY', JSON.stringify(['private'])],
    ])('throw in Unique mode, whose semantic search they cannot filter: %s', (key, value) => {
      expect(() => load({ MCP_TOOLS: tools('search_emails'), [key]: value })).toThrow(
        new RegExp(`${key}: needs MCP_BACKEND=microsoft_graph`),
      );
    });

    it('accept empty lists in Unique mode', () => {
      const config = load({
        MCP_TOOLS: tools('search_emails'),
        EXCLUDED_SENSITIVITY_LABELS: '[]',
        EXCLUDED_LEGACY_SENSITIVITY: '[]',
      });

      expect(config.sensitivityExclusions.labels.size).toBe(0);
    });
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

  it('reads every setting the same way as loadFeaturesConfig', async () => {
    const env = {
      ...READ_ONLY_ENV,
      MCP_DEBUG_MODE: 'disabled',
      UNIQUE_ATTACHMENTS: 'disabled',
      DIRECTORY_SYNC_MODE: 'on_demand',
      MICROSOFT_OFFLINE_ACCESS: 'disabled',
      MICROSOFT_PROFILE_SCOPES: 'disabled',
    };
    for (const [key, value] of Object.entries(env)) {
      vi.stubEnv(key, value);
    }

    const config = await featuresConfig();

    expect(config).toEqual(loadFeaturesConfig(env));
    expect(config).toMatchObject({ offlineAccess: false, profileScopes: false });
  });

  it('fails naming the tool in MCP_TOOLS', async () => {
    vi.stubEnv('MCP_BACKEND', 'microsoft_graph');
    vi.stubEnv('MCP_TOOLS', tools('sync_progress'));

    await expect(featuresConfig()).rejects.toThrow(/"sync_progress"/);
  });
});
