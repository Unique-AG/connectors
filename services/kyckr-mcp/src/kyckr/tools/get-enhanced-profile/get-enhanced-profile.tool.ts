import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetEnhancedProfileInputSchema,
  GetEnhancedProfileOutputSchema,
  GetEnhancedProfileQuery,
} from './get-enhanced-profile.query';
import { META } from './get-enhanced-profile-tool.meta';

@Injectable()
export class GetEnhancedProfileTool {
  public constructor(private readonly getEnhancedProfileQuery: GetEnhancedProfileQuery) {}

  @Tool({
    name: 'get_enhanced_profile',
    title: 'Get Enhanced Company Profile',
    description:
      'Fetch a paid Enhanced company profile from Kyckr using a confirmed `kyckrId`. Returns everything in `get_lite_profile` plus representatives (directors/officers), ultimate beneficial owners, share capital, contact details, and activity declarations. Use only when ownership or representative data is needed; `get_lite_profile` is cheaper for basic identification. A `statusCode: 405` response means the enhanced profile is not available synchronously for that jurisdiction — surface this limitation to the user; do not substitute `create_document_order` (which orders registry filings, not profile data).',
    parameters: GetEnhancedProfileInputSchema,
    outputSchema: GetEnhancedProfileOutputSchema,
    annotations: {
      title: 'Get Enhanced Company Profile',
      readOnlyHint: true,
      destructiveHint: false,
      // Each invocation spends Kyckr credits. Advertising idempotency would invite
      // clients/agents to retry or re-call freely, which costs money.
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getEnhancedProfile(
    input: z.infer<typeof GetEnhancedProfileInputSchema>,
    _context: Context,
  ): Promise<z.infer<typeof GetEnhancedProfileOutputSchema>> {
    return this.getEnhancedProfileQuery.run(input);
  }
}
