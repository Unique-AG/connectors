import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetCustomerSecureMessagesInputSchema = z.object({
  recordId: z.string().optional().describe("Unique identifier of an entity"),
  parentMessageId: z.string().optional().describe("Identifier of the parent message in a thread"),
  toCustomerId: z.string().optional().describe("Customer ID of the recipient"),
  fromCustomerId: z.string().optional().describe("Customer ID of the sender"),
  messageStatus: z.string().optional().describe("Status of the message"),
});

export type GetCustomerSecureMessagesInput = z.infer<typeof GetCustomerSecureMessagesInputSchema>;

export const GetCustomerSecureMessagesOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetCustomerSecureMessagesResult = z.infer<typeof GetCustomerSecureMessagesOutputSchema>;

@Injectable()
export class GetCustomerSecureMessagesQuery {
  private readonly logger = new Logger(GetCustomerSecureMessagesQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetCustomerSecureMessagesInput): Promise<GetCustomerSecureMessagesResult> {
    this.logger.debug({}, 'get_customer_secure_messages: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/party/customers/secureMessages', {
        recordId: input.recordId,
        parentMessageId: input.parentMessageId,
        toCustomerId: input.toCustomerId,
        fromCustomerId: input.fromCustomerId,
        messageStatus: input.messageStatus,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_customer_secure_messages', result, start);
    }
  }
}
