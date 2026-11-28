import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { MCP_TOOL_METADATA_KEY } from '@unique-ag/mcp-server-module';
import type { Type } from '@nestjs/common';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { getScopes } from '~/auth/microsoft.provider';
import { loadFeaturesConfig } from '~/config';
import { registerBackendModule } from '~/features/backend.module';

const FIXTURES = resolve(
  __dirname,
  '../../deploy/helm-charts/outlook-semantic-mcp/tests/deployments',
);

// What each Entra app grants today: `mail_scopes`, plus `Calendars.ReadWrite.Shared` with
// `calendar_integration = "enabled"`, in the Entra Terraform module at connectors 2a3241039.
const MAIL_GRANT = [
  'User.Read',
  'User.Read.All',
  'Mail.ReadWrite',
  'Mail.ReadWrite.Shared',
  'MailboxSettings.Read',
  'People.Read',
];
const CALENDAR_GRANT = [...MAIL_GRANT, 'Calendars.ReadWrite.Shared'];
// Requested at sign-in without being registered on the app.
const UNREGISTERED = ['openid', 'profile', 'email', 'offline_access'];

// What the settings before MCP_TOOLS registered in microsoft_graph mode, in registration order.
const LEGACY_GRAPH_TOOLS = [
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
const LEGACY_GRAPH_CALENDAR_TOOLS = [
  ...LEGACY_GRAPH_TOOLS,
  'list_calendars',
  'search_calendar_events',
  'check_availability',
  'suggest_meeting_times',
  'respond_to_invite',
  'create_event',
  'update_event',
  'cancel_event',
];

// One fixture per shape of existing deployment.
const DEPLOYMENTS: Record<string, { grant: string[]; legacyTools: string[] }> = {
  mail: { grant: MAIL_GRANT, legacyTools: LEGACY_GRAPH_TOOLS },
  'mail-calendar': { grant: CALENDAR_GRANT, legacyTools: LEGACY_GRAPH_CALENDAR_TOOLS },
  'mail-calendar-debug': { grant: CALENDAR_GRANT, legacyTools: LEGACY_GRAPH_CALENDAR_TOOLS },
};

interface DeploymentValues {
  mcpConfig: {
    app: { mcpBackend: string; mcpDebugMode?: string; tools: string[] };
    delegatedAccess: { scan: string };
  };
}

// The env `templates/_config-*.tpl` renders; tests/deployments._test.yaml pins it per fixture.
const envOf = ({ mcpConfig: { app, delegatedAccess } }: DeploymentValues) => ({
  MCP_BACKEND: app.mcpBackend,
  MCP_DEBUG_MODE: app.mcpDebugMode ?? 'disabled',
  MCP_TOOLS: JSON.stringify(app.tools),
  DELEGATED_ACCESS_SCAN: delegatedAccess.scan,
});

const toolNameOf = (toolClass: Type): string | undefined =>
  Object.getOwnPropertyNames(toolClass.prototype)
    .map((key) => Reflect.getMetadata(MCP_TOOL_METADATA_KEY, toolClass.prototype[key]))
    .find(Boolean)?.name;

const fixtures = readdirSync(FIXTURES)
  .filter((file) => file.endsWith('.values.json'))
  .map((file) => ({
    name: file.replace('.values.json', ''),
    values: JSON.parse(readFileSync(join(FIXTURES, file), 'utf8')) as DeploymentValues,
  }));

describe('existing deployments', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('has an expectation for every deployment fixture', () => {
    expect(fixtures.map(({ name }) => name).sort()).toEqual(Object.keys(DEPLOYMENTS).sort());
  });

  describe.each(fixtures)('$name', ({ name, values }) => {
    const expected = DEPLOYMENTS[name];

    it('registers the tools the settings before MCP_TOOLS registered for it', () => {
      const module = registerBackendModule(loadFeaturesConfig(envOf(values)));
      const tools = (module.providers ?? []).flatMap((provider) => {
        const toolName = typeof provider === 'function' ? toolNameOf(provider) : undefined;
        return toolName ? [toolName] : [];
      });

      expect(tools).toEqual(expected?.legacyTools);
    });

    it('requests exactly what its Entra app grants, so no new consent is needed', () => {
      for (const [key, value] of Object.entries(envOf(values))) {
        vi.stubEnv(key, value);
      }

      expect([...getScopes()].sort()).toEqual([...(expected?.grant ?? []), ...UNREGISTERED].sort());
    });
  });
});
