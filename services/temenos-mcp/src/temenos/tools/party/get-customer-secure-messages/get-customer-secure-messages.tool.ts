import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetCustomerSecureMessagesInputSchema,
  GetCustomerSecureMessagesOutputSchema,
  GetCustomerSecureMessagesQuery,
  type GetCustomerSecureMessagesResult,
} from './get-customer-secure-messages.query';
import { META } from './get-customer-secure-messages-tool.meta';

@Injectable()
export class GetCustomerSecureMessagesTool {
  public constructor(private readonly query: GetCustomerSecureMessagesQuery) {}

  @Tool({
    name: 'get_customer_secure_messages',
    title: 'Get Customer Secure Messages',
    description: 'Retrieve secure messages between customers and the bank from Temenos.',
    parameters: GetCustomerSecureMessagesInputSchema,
    outputSchema: GetCustomerSecureMessagesOutputSchema,
    annotations: {
      title: 'Get Customer Secure Messages',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getCustomerSecureMessages(
    input: z.infer<typeof GetCustomerSecureMessagesInputSchema>,
    _context: Context,
  ): Promise<GetCustomerSecureMessagesResult> {
    return this.query.run(input);
  }
}
