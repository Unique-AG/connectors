import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { RunSyncDiagnosticsQuery } from './run-sync-diagnostics.query';

const META = createMeta({
  icon: 'search',
  systemPrompt:
    'Runs a point-in-time diagnostic comparing the Microsoft mailbox against what Unique has ingested. Use when a user reports missing emails or unexpected content.',
});

const InputSchema = z.object({});

const emailDiagnosticEntrySchema = z.object({
  messageId: z.string(),
  fileKey: z.string(),
});

const OutputSchema = z.object({
  messageIdsSkippedBecauseOfFilters: z.array(emailDiagnosticEntrySchema),
  messageIdsFoundInMicrosoftButNotFoundInUnique: z.array(emailDiagnosticEntrySchema),
  messageIdsFoundInUniqueButNotFoundInMicrosoft: z.array(emailDiagnosticEntrySchema),
});

@Injectable()
export class SyncDiagnosticsTool {
  public constructor(private readonly runSyncDiagnosticsQuery: RunSyncDiagnosticsQuery) {}

  @Tool({
    name: 'sync_diagnostics',
    title: 'Sync Diagnostics',
    description:
      'Point-in-time snapshot comparing the Microsoft mailbox against the Unique knowledge base. Returns which emails were skipped by filters, which are missing from Unique, and which are in Unique but no longer in Microsoft.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Sync Diagnostics',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async syncDiagnostics(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.infer<typeof OutputSchema>> {
    const userProfileId = extractUserProfileId(request).toString();
    return await this.runSyncDiagnosticsQuery.run(userProfileId);
  }
}
