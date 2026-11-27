import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, MCP_TOOL_METADATA_KEY } from '@unique-ag/mcp-server-module';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import type * as z from 'zod';
import { loadFeaturesConfig } from '~/config';
import { BuildWebLinksCommand } from '~/features/graph-utils/build-web-links.command';
import { SensitivityFilter, SensitivityVerdict } from '../../sensitivity-filter';
import { OpenEmailQuery } from '../open-email.query';
import { OpenEmailTool } from '../open-email.tool';

vi.mock('~/utils/extract-user-profile-id', () => ({
  extractUserProfileId: () => ({ toString: () => 'user-1' }),
}));

const request = {} as McpAuthenticatedRequest;
const context = {} as Context;

describe('OpenEmailTool', () => {
  let openEmailQuery: { run: Mock };
  let tool: OpenEmailTool;

  beforeEach(() => {
    openEmailQuery = { run: vi.fn() };
    tool = new OpenEmailTool(
      { run: vi.fn() } as never,
      openEmailQuery as never,
      { run: vi.fn().mockResolvedValue(undefined) } as never,
      loadFeaturesConfig({
        MCP_BACKEND: 'microsoft_graph',
        MCP_TOOLS: JSON.stringify(['open_email']),
        DELEGATED_ACCESS_SCAN: 'disabled',
      }),
      { run: vi.fn().mockResolvedValue({ allowed: true }) } as never,
    );
  });

  it.each([404, 400])('tells the agent to search again when Graph answers %s', async (status) => {
    openEmailQuery.run.mockRejectedValue(new GraphError(status, 'Not found'));

    const result = await tool.openEmailById({ id: 'cont_old' }, context, request);

    expect(result).toEqual({
      success: false,
      message: expect.stringContaining('Run `search_emails` again'),
    });
  });

  it('returns the email with its subject as title and its Outlook web link', async () => {
    const webLink = 'https://outlook.office365.com/owa/?ItemID=AAMk&exvsurl=1';
    openEmailQuery.run.mockResolvedValue({
      id: 'msg-1',
      title: 'Budget Q3',
      webLink,
      metadata: { from: 'alex@example.com', isDraft: false },
      text: 'Numbers for the quarter.',
      bodyContentType: 'text',
    });

    const result = await tool.openEmailById({ id: 'msg-1' }, context, request);

    expect(result).toEqual({
      success: true,
      title: 'Budget Q3',
      webLink,
      emailData: {
        id: 'msg-1',
        title: 'Budget Q3',
        metadata: { from: 'alex@example.com', isDraft: false },
        text: 'Numbers for the quarter.',
        bodyContentType: 'text',
      },
    });
  });

  it('leaves out the top-level title when the email has no web link', async () => {
    openEmailQuery.run.mockResolvedValue({
      id: 'msg-3',
      title: 'Budget Q3',
      webLink: null,
      metadata: null,
      text: 'Hi',
      bodyContentType: 'text',
    });

    const result = await tool.openEmailById({ id: 'msg-3' }, context, request);

    expect(result.title).toBeUndefined();
    expect(result).toMatchObject({
      success: true,
      webLink: null,
      emailData: { title: 'Budget Q3' },
    });
  });

  it('names the label of a message withheld for its sensitivity and points to Outlook', async () => {
    openEmailQuery.run.mockResolvedValue({
      withheld: {
        verdict: SensitivityVerdict.Excluded,
        label: 'Confidential Encrypted',
        configuredById: false,
      },
    });

    const result = await tool.openEmailById({ id: 'msg-labelled' }, context, request);

    expect(result).toEqual({
      success: false,
      message:
        'This email is withheld because of its sensitivity label "Confidential Encrypted". Its content cannot be shown here; the user can read it in Outlook.',
    });
  });

  it('says the name of a label excluded by id is not known', async () => {
    openEmailQuery.run.mockResolvedValue({
      withheld: {
        verdict: SensitivityVerdict.Excluded,
        label: '4f1c2a7e-9b3d-4e85-a6c0-d2b71e93f5a8',
        configuredById: true,
      },
    });

    const result = await tool.openEmailById({ id: 'msg-labelled' }, context, request);

    expect(result).toEqual({
      success: false,
      message:
        "This email is withheld because of a sensitivity label excluded by its id (4f1c2a7e-9b3d-4e85-a6c0-d2b71e93f5a8); the label's name is not known, because the exclusion is configured by id. Its content cannot be shown here; the user can read it in Outlook.",
    });
  });

  it('says when a message is withheld because its sensitivity label could not be read', async () => {
    openEmailQuery.run.mockResolvedValue({ withheld: { verdict: SensitivityVerdict.Unreadable } });

    const result = await tool.openEmailById({ id: 'msg-unreadable' }, context, request);

    expect(result).toEqual({
      success: false,
      message:
        'This email is withheld because its sensitivity label could not be read. Its content cannot be shown here; the user can read it in Outlook.',
    });
  });

  it('rethrows any other Graph failure', async () => {
    const error = new GraphError(503, 'Unavailable');
    openEmailQuery.run.mockRejectedValue(error);

    await expect(tool.openEmailById({ id: 'msg-1' }, context, request)).rejects.toBe(error);
  });
});

describe('OpenEmailTool input', () => {
  const READ_ONLY_ENV = {
    MCP_BACKEND: 'microsoft_graph',
    DELEGATED_ACCESS_SCAN: 'disabled',
    UNIQUE_ATTACHMENTS: 'disabled',
    MCP_TOOLS: JSON.stringify(['open_email']),
  };

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  async function loadToolWith(env: Record<string, string>) {
    for (const [key, value] of Object.entries(env)) {
      vi.stubEnv(key, value);
    }
    vi.resetModules();
    const module = await import('../open-email.tool');
    const metadata: { parameters: z.ZodObject; description: string } = Reflect.getMetadata(
      MCP_TOOL_METADATA_KEY,
      module.OpenEmailTool.prototype.openEmailById,
    );
    return {
      OpenEmailToolClass: module.OpenEmailTool,
      schema: metadata.parameters,
      description: metadata.description,
    };
  }

  it('offers and describes the ingested chunk params in Unique mode', async () => {
    const { schema, description } = await loadToolWith({
      MCP_BACKEND: 'microsoft_graph_and_unique_api',
    });

    expect(Object.keys(schema.shape)).toEqual(
      expect.arrayContaining(['uniqueContentId', 'chunkIds']),
    );
    expect(description).toContain('`uniqueContentId` and `chunkIds`');
  });

  it('neither offers nor describes the ingested chunk params in microsoft_graph mode', async () => {
    const { schema, description } = await loadToolWith(READ_ONLY_ENV);

    expect(Object.keys(schema.shape)).not.toContain('uniqueContentId');
    expect(Object.keys(schema.shape)).not.toContain('chunkIds');
    expect(description).not.toMatch(/uniqueContentId|chunkIds|chunks/);
  });

  it('opens an email in microsoft_graph mode with Unique off without calling Unique', async () => {
    const { OpenEmailToolClass, schema } = await loadToolWith(READ_ONLY_ENV);
    const graphRequest = {
      header: vi.fn().mockReturnThis(),
      select: vi.fn().mockReturnThis(),
      expand: vi.fn().mockReturnThis(),
      get: vi.fn().mockResolvedValue({ id: 'msg-1', body: { content: 'Hello' } }),
    };
    const getContentById = vi.fn();
    const openEmail = new OpenEmailToolClass(
      { run: vi.fn() } as never,
      new OpenEmailQuery(
        { createClientForUser: () => ({ api: () => graphRequest }) } as never,
        { content: { getContentById } } as never,
        { run: vi.fn().mockResolvedValue({ id: 'user-1', email: 'own@example.com' }) } as never,
        new BuildWebLinksCommand({ run: vi.fn().mockResolvedValue(new Map()) } as never),
        new SensitivityFilter(loadFeaturesConfig(READ_ONLY_ENV)),
      ),
      { run: vi.fn().mockResolvedValue(undefined) } as never,
      loadFeaturesConfig(READ_ONLY_ENV),
      { run: vi.fn().mockResolvedValue({ allowed: true }) } as never,
    );

    const input = schema.parse({
      id: 'msg-1',
      uniqueContentId: 'cont-1',
      chunkIds: ['chunk-1'],
    }) as Parameters<OpenEmailTool['openEmailById']>[0];
    const result = await openEmail.openEmailById(input, context, request);

    expect(result).toMatchObject({ success: true, emailData: { id: 'msg-1', text: 'Hello' } });
    expect(getContentById).not.toHaveBeenCalled();
  });
});
