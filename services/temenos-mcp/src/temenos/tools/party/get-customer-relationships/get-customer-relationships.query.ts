import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { Metrics } from '../../../metrics';

export const GetCustomerRelationshipsInputSchema = z.object({
  customerRelationGroupId: z.string().optional().describe("Key to the customer relationship group"),
  partyId: z.string().optional().describe("Customer or person entity ID that is part of the relationship"),
  relationPartyId: z.string().optional().describe("Related customer or person entity ID"),
  recordId: z.string().optional().describe("Unique identifier of an entity"),
});

export type GetCustomerRelationshipsInput = z.infer<typeof GetCustomerRelationshipsInputSchema>;

export const GetCustomerRelationshipsOutputSchema = z
  .object({
    success: z.boolean(),
    data: z.unknown().optional(),
    statusCode: z.number().optional(),
    message: z.string().optional(),
  })
  .loose();

export type GetCustomerRelationshipsResult = z.infer<typeof GetCustomerRelationshipsOutputSchema>;

@Injectable()
export class GetCustomerRelationshipsQuery {
  private readonly logger = new Logger(GetCustomerRelationshipsQuery.name);

  public constructor(
    private readonly client: TemenosHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetCustomerRelationshipsInput): Promise<GetCustomerRelationshipsResult> {
    this.logger.debug({}, 'get_customer_relationships: invoked');
    const start = Date.now();
    let result: 'success' | 'error' = 'success';
    try {
      const data = await this.client.get<unknown>('/party/customers/relationships', {
        customerRelationGroupId: input.customerRelationGroupId,
        partyId: input.partyId,
        relationPartyId: input.relationPartyId,
        recordId: input.recordId,
      });
      return { success: true, data };
    } catch (err) {
      result = 'error';
      if (err instanceof TemenosApiError) {
        return { success: false, statusCode: err.status, message: err.message };
      }
      throw err;
    } finally {
      this.metrics.recordToolDuration('get_customer_relationships', result, start);
    }
  }
}
