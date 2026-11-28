import { describe, expect, it } from 'vitest';
import { loadFeaturesConfig } from '../features.config';
import { resolveScopes } from '../graph-permissions';

// Literal expected scopes, the fixed list earlier versions requested; never derived from the code under test.
const EARLIER_MAIL_SCOPES = [
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
const EARLIER_CALENDAR_SCOPES = ['Calendars.ReadWrite.Shared'];

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
    ])('equals the scopes earlier versions requested in %s mode', (backend, tools) => {
      expect(scopesFor({ MCP_BACKEND: backend, MCP_TOOLS: JSON.stringify(tools) })).toEqual(
        sorted(EARLIER_MAIL_SCOPES),
      );
    });

    it('adds only Calendars.ReadWrite.Shared when the calendar tools are listed', () => {
      expect(scopesFor({ MCP_TOOLS: JSON.stringify([...MAIL_TOOLS, ...CALENDAR_TOOLS]) })).toEqual(
        sorted([...EARLIER_MAIL_SCOPES, ...EARLIER_CALENDAR_SCOPES]),
      );
    });
  });

  describe("today's tools with DELEGATED_ACCESS_SCAN=disabled", () => {
    it('equals the scopes earlier versions requested without Mail.ReadWrite.Shared and User.Read.All', () => {
      expect(
        scopesFor({ DELEGATED_ACCESS_SCAN: 'disabled', MCP_TOOLS: JSON.stringify(MAIL_TOOLS) }),
      ).toEqual(sorted(without(EARLIER_MAIL_SCOPES, 'Mail.ReadWrite.Shared', 'User.Read.All')));
    });

    it('adds only Calendars.ReadWrite.Shared when the calendar tools are listed', () => {
      expect(
        scopesFor({
          DELEGATED_ACCESS_SCAN: 'disabled',
          MCP_TOOLS: JSON.stringify([...MAIL_TOOLS, ...CALENDAR_TOOLS]),
        }),
      ).toEqual(
        sorted([
          ...without(EARLIER_MAIL_SCOPES, 'Mail.ReadWrite.Shared', 'User.Read.All'),
          ...EARLIER_CALENDAR_SCOPES,
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

    it('requests only the four read permissions and openid with offline access and profile scopes off', () => {
      expect(
        scopesFor({
          ...readOnly,
          DIRECTORY_SYNC_MODE: 'on_demand',
          MICROSOFT_OFFLINE_ACCESS: 'disabled',
          MICROSOFT_PROFILE_SCOPES: 'disabled',
        }),
      ).toEqual(
        sorted(['openid', 'User.Read', 'Mail.Read', 'People.Read', 'MailboxSettings.Read']),
      );
    });

    it('drops only offline_access with offline access off', () => {
      expect(
        scopesFor({
          ...readOnly,
          DIRECTORY_SYNC_MODE: 'on_demand',
          MICROSOFT_OFFLINE_ACCESS: 'disabled',
        }),
      ).toEqual(without(scopesFor(readOnly), 'offline_access'));
    });

    it('drops only profile and email with profile scopes off', () => {
      expect(scopesFor({ ...readOnly, MICROSOFT_PROFILE_SCOPES: 'disabled' })).toEqual(
        without(scopesFor(readOnly), 'profile', 'email'),
      );
    });

    it('requests the four read permissions with offline access and profile scopes on by default', () => {
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

  describe('each permission follows the tools that need it', () => {
    const minimal = (...tools: string[]) =>
      scopesFor({
        MCP_BACKEND: 'microsoft_graph',
        DELEGATED_ACCESS_SCAN: 'disabled',
        MCP_TOOLS: JSON.stringify(tools),
      });
    const SIGN_IN = ['openid', 'profile', 'email', 'offline_access', 'User.Read', 'Mail.Read'];

    it('requests only the base for a tool that reads the folder cache', () => {
      expect(minimal('list_mailboxes_and_directories')).toEqual(sorted(SIGN_IN));
    });

    it('requests People.Read only with lookup_contacts', () => {
      expect(minimal('lookup_contacts')).toEqual(sorted([...SIGN_IN, 'People.Read']));
      expect(minimal(...without(READ_ONLY_TOOLS, 'lookup_contacts'))).not.toContain('People.Read');
    });

    it('requests MailboxSettings.Read for the categories and the time zone of search', () => {
      expect(minimal('list_categories')).toEqual(sorted([...SIGN_IN, 'MailboxSettings.Read']));
      expect(minimal('open_email')).toEqual(sorted([...SIGN_IN, 'MailboxSettings.Read']));
      expect(minimal('lookup_contacts')).not.toContain('MailboxSettings.Read');
    });

    it('requests the calendar permission and the time zone for a calendar search', () => {
      expect(minimal('search_calendar_events')).toEqual(
        sorted([...SIGN_IN, 'Calendars.ReadWrite.Shared', 'MailboxSettings.Read']),
      );
      expect(minimal('respond_to_invite')).toEqual(
        sorted([...SIGN_IN, 'Calendars.ReadWrite.Shared']),
      );
    });
  });

  it('is sorted, so the scope string is the same on every start', () => {
    const scopes = scopesFor({ MCP_TOOLS: JSON.stringify([...CALENDAR_TOOLS, ...MAIL_TOOLS]) });

    expect(scopes).toEqual(sorted(scopes));
  });
});
