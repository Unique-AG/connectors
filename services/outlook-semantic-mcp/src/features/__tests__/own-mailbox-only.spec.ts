import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import type { Context } from '@unique-ag/mcp-server-module';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, type Mock, vi } from 'vitest';
import { loadFeaturesConfig } from '~/config';
import { OpenEmailTool } from '../content/open-email/open-email.tool';
import { AddAttachmentsToDraftEmailTool } from '../email-management/tools/add-attachments-to-draft-email.tool';
import { CreateDraftEmailTool } from '../email-management/tools/create-draft-email.tool';
import { RemoveAttachmentsFromDraftEmailTool } from '../email-management/tools/remove-attachments-from-draft-email.tool';
import { UpdateDraftEmailTool } from '../email-management/tools/update-draft-email.tool';
import { CheckMailboxAccessQuery } from '../user-utils/check-mailbox-access.query';

const OWN_EMAIL = 'ada@example.com';
const OTHER_MAILBOX = 'shared@example.com';
const request = {
  user: { userProfileId: 'user_profile_01h455vb4pex5vsknk084sn02q' },
} as unknown as McpAuthenticatedRequest;
const context = { mcpRequest: { params: {} } } as unknown as Context;

const features = loadFeaturesConfig({
  MCP_BACKEND: 'microsoft_graph',
  DELEGATED_ACCESS_SCAN: 'disabled',
  MCP_TOOLS: JSON.stringify([
    'draft_email',
    'update_draft_email',
    'add_attachments_to_draft_email',
    'remove_attachments_from_draft_email',
    'open_email',
  ]),
});

interface ToolUnderTest {
  call: (mailbox: string) => Promise<unknown>;
  // The dependencies that reach Microsoft Graph, first one called on the allowed path.
  graph: Mock[];
}

const build = (name: string): ToolUnderTest => {
  const guard = new CheckMailboxAccessQuery(features, {
    run: vi.fn().mockResolvedValue({ email: OWN_EMAIL }),
  } as never);
  const failedDraftState = { status: 'failed', message: 'not a draft' };

  switch (name) {
    case 'draft_email': {
      const command = vi.fn().mockResolvedValue({ success: true, message: 'created' });
      const tool = new CreateDraftEmailTool({ run: command } as never, guard);
      return {
        call: (mailbox) =>
          tool.createDraftEmail(
            { mailbox, recipientsData: { type: 'draft' } } as never,
            context,
            request,
          ),
        graph: [command],
      };
    }
    case 'update_draft_email': {
      const command = vi.fn().mockResolvedValue({ success: true, message: 'updated' });
      const tool = new UpdateDraftEmailTool({ run: command } as never, guard);
      return {
        call: (mailbox) =>
          tool.updateDraftEmail({ draftId: 'draft-1', mailbox } as never, context, request),
        graph: [command],
      };
    }
    case 'add_attachments_to_draft_email': {
      const draftState = vi.fn().mockResolvedValue(failedDraftState);
      const command = vi.fn();
      const tool = new AddAttachmentsToDraftEmailTool(
        { run: draftState } as never,
        { run: command } as never,
        guard,
      );
      return {
        call: (mailbox) =>
          tool.addAttachments({ draftId: 'draft-1', mailbox } as never, context, request),
        graph: [draftState, command],
      };
    }
    case 'remove_attachments_from_draft_email': {
      const draftState = vi.fn().mockResolvedValue(failedDraftState);
      const command = vi.fn();
      const tool = new RemoveAttachmentsFromDraftEmailTool(
        { run: draftState } as never,
        { run: command } as never,
        guard,
      );
      return {
        call: (mailbox) =>
          tool.removeAttachments(
            { draftId: 'draft-1', fileNames: ['a.pdf'], mailbox } as never,
            context,
            request,
          ),
        graph: [draftState, command],
      };
    }
    default: {
      const openEmail = vi.fn().mockRejectedValue(new GraphError(404, 'Not found'));
      const timezone = vi.fn().mockResolvedValue(undefined);
      const tool = new OpenEmailTool(
        { run: vi.fn() } as never,
        { run: openEmail } as never,
        { run: timezone } as never,
        features,
        guard,
      );
      return {
        call: (mailbox) =>
          tool.openEmailById({ id: 'message-1', mailbox } as never, context, request),
        graph: [openEmail, timezone],
      };
    }
  }
};

describe('tools with a mailbox parameter when DELEGATED_ACCESS_SCAN=disabled', () => {
  describe.each([
    'draft_email',
    'update_draft_email',
    'add_attachments_to_draft_email',
    'remove_attachments_from_draft_email',
    'open_email',
  ])('%s', (name) => {
    it('refuses another mailbox before calling Graph', async () => {
      const { call, graph } = build(name);

      const result = await call(OTHER_MAILBOX);

      expect(result).toEqual({
        success: false,
        message: expect.stringContaining(`your own mailbox (${OWN_EMAIL})`),
      });
      for (const dependency of graph) {
        expect(dependency).not.toHaveBeenCalled();
      }
    });

    it("works with the user's own address", async () => {
      const { call, graph } = build(name);

      await call(OWN_EMAIL);

      expect(graph[0]).toHaveBeenCalled();
    });
  });
});
