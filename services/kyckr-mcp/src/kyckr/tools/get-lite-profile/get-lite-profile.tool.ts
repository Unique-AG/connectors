import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetLiteProfileInputSchema,
  GetLiteProfileOutputSchema,
  GetLiteProfileQuery,
} from './get-lite-profile.query';
import { META } from './get-lite-profile-tool.meta';

@Injectable()
export class GetLiteProfileTool {
  public constructor(private readonly getLiteProfileQuery: GetLiteProfileQuery) {}

  @Tool({
    name: 'get_lite_profile',
    title: 'Get Lite Company Profile',
    description:
      'Fetch a paid Lite company profile from Kyckr using a confirmed `kyckrId`. Use this when basic verified registry details are needed: company name, registration number, registered address, registration/foundation dates, legal form, legal status, activities, and registration authority. This call may consume Kyckr credits. It does not return directors, shareholders, or beneficial owners; use `get_enhanced_profile` for ownership and officer data. Always inspect `success`; Kyckr errors are returned as `{ success: false, statusCode, message, correlationId }`.',
    parameters: GetLiteProfileInputSchema,
    outputSchema: GetLiteProfileOutputSchema,
    annotations: {
      title: 'Get Lite Company Profile',
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
  public async getLiteProfile(
    input: z.infer<typeof GetLiteProfileInputSchema>,
    _context: Context,
  ): Promise<z.infer<typeof GetLiteProfileOutputSchema>> {
    return this.getLiteProfileQuery.run(input);
  }
}
