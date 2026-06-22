import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetExternalUserPreferencesInputSchema,
  GetExternalUserPreferencesOutputSchema,
  GetExternalUserPreferencesQuery,
  type GetExternalUserPreferencesResult,
} from './get-external-user-preferences.query';
import { META } from './get-external-user-preferences-tool.meta';

@Injectable()
export class GetExternalUserPreferencesTool {
  public constructor(private readonly query: GetExternalUserPreferencesQuery) {}

  @Tool({
    name: 'get_external_user_preferences',
    title: 'Get External User Preferences',
    description: 'Retrieve external user preference settings from Temenos.',
    parameters: GetExternalUserPreferencesInputSchema,
    outputSchema: GetExternalUserPreferencesOutputSchema,
    annotations: {
      title: 'Get External User Preferences',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getExternalUserPreferences(
    input: z.infer<typeof GetExternalUserPreferencesInputSchema>,
    _context: Context,
  ): Promise<GetExternalUserPreferencesResult> {
    return this.query.run(input as never);
  }
}
