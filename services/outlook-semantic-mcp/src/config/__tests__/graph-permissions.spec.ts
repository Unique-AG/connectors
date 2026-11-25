import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { loadFeaturesConfig } from '../features.config';
import { resolveScopes } from '../graph-permissions';
import { GRAPH_PERMISSIONS } from '../tool-declarations';

// main's MAIL_SCOPES and CALENDAR_SCOPES (src/auth/microsoft.provider.ts), copied, not derived.
const MAIN_MAIL_SCOPES = [
  'openid',
  'profile',
  'email',
  'offline_access',
  'User.Read',
  'User.Read.All',
  'MailboxSettings.Read',
  'Mail.ReadWrite',
  'Mail.ReadWrite.Shared',
  'People.Read',
];
const MAIN_CALENDAR_SCOPES = ['Calendars.ReadWrite.Shared'];

const MAIL_TOOLS = [
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
const SYNC_TOOLS = [
  'sync_progress',
  'verify_inbox_connection',
  'delete_inbox_data',
  'reconnect_inbox',
];
const CALENDAR_TOOLS = [
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

const scopesFor = (env: NodeJS.ProcessEnv) =>
  resolveScopes(
    loadFeaturesConfig({
      MCP_BACKEND: 'microsoft_graph_and_unique_api',
      DELEGATED_ACCESS_SCAN: 'full_access_only',
      ...env,
    }),
  );

const sorted = (scopes: string[]) => [...scopes].sort();
const without = (scopes: string[], ...removed: string[]) =>
  scopes.filter((scope) => !removed.includes(scope));

describe(resolveScopes.name, () => {
  describe("today's tools with shared mailboxes on", () => {
    it.each([
      ['microsoft_graph_and_unique_api', [...MAIL_TOOLS, ...SYNC_TOOLS]],
      ['microsoft_graph', MAIL_TOOLS],
    ])('equals main’s MAIL_SCOPES in %s mode', (backend, tools) => {
      expect(scopesFor({ MCP_BACKEND: backend, MCP_TOOLS: JSON.stringify(tools) })).toEqual(
        sorted(MAIN_MAIL_SCOPES),
      );
    });

    it('adds only Calendars.ReadWrite.Shared when the calendar tools are listed', () => {
      expect(scopesFor({ MCP_TOOLS: JSON.stringify([...MAIL_TOOLS, ...CALENDAR_TOOLS]) })).toEqual(
        sorted([...MAIN_MAIL_SCOPES, ...MAIN_CALENDAR_SCOPES]),
      );
    });
  });

  describe("today's tools with DELEGATED_ACCESS_SCAN=disabled", () => {
    it('equals main’s MAIL_SCOPES without Mail.ReadWrite.Shared and User.Read.All', () => {
      expect(
        scopesFor({ DELEGATED_ACCESS_SCAN: 'disabled', MCP_TOOLS: JSON.stringify(MAIL_TOOLS) }),
      ).toEqual(sorted(without(MAIN_MAIL_SCOPES, 'Mail.ReadWrite.Shared', 'User.Read.All')));
    });

    it('adds only Calendars.ReadWrite.Shared when the calendar tools are listed', () => {
      expect(
        scopesFor({
          DELEGATED_ACCESS_SCAN: 'disabled',
          MCP_TOOLS: JSON.stringify([...MAIL_TOOLS, ...CALENDAR_TOOLS]),
        }),
      ).toEqual(
        sorted([
          ...without(MAIN_MAIL_SCOPES, 'Mail.ReadWrite.Shared', 'User.Read.All'),
          ...MAIN_CALENDAR_SCOPES,
        ]),
      );
    });
  });

  describe('the read-only deployment', () => {
    const readOnly = {
      MCP_BACKEND: 'microsoft_graph',
      DELEGATED_ACCESS_SCAN: 'disabled',
      MCP_TOOLS: JSON.stringify(READ_ONLY_TOOLS),
    };

    it('requests only the four read permissions', () => {
      expect(scopesFor(readOnly)).toEqual(
        sorted([
          'openid',
          'profile',
          'email',
          'offline_access',
          'User.Read',
          'Mail.Read',
          'People.Read',
          'MailboxSettings.Read',
        ]),
      );
    });

    it('requests Mail.ReadWrite instead of Mail.Read with it as an extra permission', () => {
      const scopes = scopesFor({
        ...readOnly,
        MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS: JSON.stringify(['Mail.ReadWrite']),
      });

      expect(scopes).toContain('Mail.ReadWrite');
      expect(scopes).not.toContain('Mail.Read');
      expect(scopes).not.toContain('Mail.ReadWrite.Shared');
    });
  });

  it('requests Mail.Read.Shared, not Mail.ReadWrite.Shared, for read tools with shared mailboxes on', () => {
    const scopes = scopesFor({
      MCP_BACKEND: 'microsoft_graph',
      MCP_TOOLS: JSON.stringify(READ_ONLY_TOOLS),
    });

    expect(scopes).toEqual(
      sorted([
        'openid',
        'profile',
        'email',
        'offline_access',
        'User.Read',
        'User.Read.All',
        'Mail.Read',
        'Mail.Read.Shared',
        'People.Read',
        'MailboxSettings.Read',
      ]),
    );
  });

  it('is sorted, so the scope string is the same on every start', () => {
    const scopes = scopesFor({ MCP_TOOLS: JSON.stringify([...CALENDAR_TOOLS, ...MAIL_TOOLS]) });

    expect(scopes).toEqual(sorted(scopes));
  });
});

describe('MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS', () => {
  it('throws at startup naming an unknown permission', () => {
    expect(() =>
      scopesFor({
        MCP_TOOLS: JSON.stringify(MAIL_TOOLS),
        MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS: JSON.stringify(['Mail.Send']),
      }),
    ).toThrow('MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS: unknown permission "Mail.Send"');
  });

  it('throws asking for a JSON array when it is not one', () => {
    expect(() =>
      scopesFor({
        MCP_TOOLS: JSON.stringify(MAIL_TOOLS),
        MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS: 'Mail.ReadWrite',
      }),
    ).toThrow('MICROSOFT_ADDITIONAL_GRAPH_PERMISSIONS: a JSON array of Graph permission names');
  });
});

describe('the Helm values schema', () => {
  it('allows exactly the known Graph permissions in additionalGraphPermissions', () => {
    const schema = JSON.parse(
      readFileSync(
        resolve(
          __dirname,
          '../../../deploy/helm-charts/outlook-semantic-mcp/values.additional.schema.json',
        ),
        'utf8',
      ),
    );
    const allowed =
      schema.properties.mcpConfig.properties.microsoft.properties.additionalGraphPermissions.items
        .enum;

    expect([...allowed].sort()).toEqual([...GRAPH_PERMISSIONS].sort());
  });
});
