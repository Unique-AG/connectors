/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@unique-ag/mcp-server-module', () => ({
  Tool: () => (_target: any, _key: string, _descriptor: PropertyDescriptor) => _descriptor,
  createMeta: () => ({}),
}));

vi.mock('nestjs-otel', async (importOriginal) => {
  const actual = await importOriginal<typeof import('nestjs-otel')>();
  return {
    ...actual,
    Span: () => (_target: any, _key: string, _descriptor: PropertyDescriptor) => _descriptor,
  };
});

import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import type { SubscriptionCreateService } from '../../subscriptions/subscription-create.service';
import { ReconnectInboxTool } from '../../subscriptions/tools/reconnect-inbox.tool';
import type { IsInboxDeletingQuery } from '../is-inbox-deleting.query';

const userProfileId = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

const makeRequest = (): McpAuthenticatedRequest =>
  ({ user: { userProfileId } }) as unknown as McpAuthenticatedRequest;

const makeTool = (deps: {
  isInboxDeleting?: Partial<IsInboxDeletingQuery>;
  subscriptionCreate?: Partial<SubscriptionCreateService>;
}) => {
  const isInboxDeleting = {
    run: vi.fn().mockResolvedValue(false),
    ...deps.isInboxDeleting,
  };
  const subscriptionCreate = {
    subscribe: vi.fn().mockResolvedValue({
      status: 'already_active',
      subscription: {
        id: 'sub-id-1',
        subscriptionId: 'graph-sub-id',
        expiresAt: new Date(Date.now() + 60 * 60 * 1000),
        userProfileId,
        createdAt: new Date(),
        updatedAt: new Date(),
      },
    }),
    ...deps.subscriptionCreate,
  };

  return new ReconnectInboxTool(
    subscriptionCreate as unknown as SubscriptionCreateService,
    isInboxDeleting as unknown as IsInboxDeletingQuery,
  );
};

describe('ReconnectInboxTool (guard: deletingInboxStartedAt)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns deletion-in-progress message when deletingInboxStartedAt is set', async () => {
    const isInboxDeleting = { run: vi.fn().mockResolvedValue(true) };
    const subscriptionCreate = { subscribe: vi.fn() };
    const tool = makeTool({ isInboxDeleting, subscriptionCreate });

    const result = await tool.reconnectInbox({}, {} as any, makeRequest());

    expect(result).toEqual({
      success: false,
      message:
        'Inbox deletion is in progress. Please wait until deletion completes before performing this action.',
      subscription: null,
    });
    expect(subscriptionCreate.subscribe).not.toHaveBeenCalled();
  });

  it('proceeds normally when deletingInboxStartedAt is null', async () => {
    const subscriptionCreate = {
      subscribe: vi.fn().mockResolvedValue({
        status: 'already_active',
        subscription: {
          id: 'sub-id-1',
          subscriptionId: 'graph-sub-id',
          expiresAt: new Date(Date.now() + 60 * 60 * 1000),
          userProfileId,
          createdAt: new Date(),
          updatedAt: new Date(),
        },
      }),
    };
    const tool = makeTool({ subscriptionCreate });

    const result = await tool.reconnectInbox({}, {} as any, makeRequest());

    expect(subscriptionCreate.subscribe).toHaveBeenCalledOnce();
    expect(result).toMatchObject({ success: true });
  });
});
