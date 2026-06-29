import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetParticipantsInputSchema,
  GetParticipantsOutputSchema,
  GetParticipantsQuery,
  type GetParticipantsResult,
} from './get-participants.query';
import { META } from './get-participants-tool.meta';

@Injectable()
export class GetParticipantsTool {
  public constructor(private readonly query: GetParticipantsQuery) {}

  @Tool({
    name: 'get_participants',
    title: 'Get Participants',
    description:
      'Retrieve participant list from Temenos. Filter by record ID, account officer, or user.',
    parameters: GetParticipantsInputSchema,
    outputSchema: GetParticipantsOutputSchema,
    annotations: {
      title: 'Get Participants',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getParticipants(
    input: z.infer<typeof GetParticipantsInputSchema>,
    _context: Context,
  ): Promise<GetParticipantsResult> {
    return this.query.run(input);
  }
}
