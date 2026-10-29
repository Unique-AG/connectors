import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import type { Context } from '@unique-ag/mcp-server-module';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { OpenEmailTool } from '../open-email.tool';

vi.mock('~/utils/extract-user-profile-id', () => ({
  extractUserProfileId: () => ({ toString: () => 'user-1' }),
}));
vi.mock('~/utils/backend-config.utils', () => ({ isMicrosoftGraphBackend: () => true }));

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

  it('rethrows any other Graph failure', async () => {
    const error = new GraphError(503, 'Unavailable');
    openEmailQuery.run.mockRejectedValue(error);

    await expect(tool.openEmailById({ id: 'msg-1' }, context, request)).rejects.toBe(error);
  });
});
