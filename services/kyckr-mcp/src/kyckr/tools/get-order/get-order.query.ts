import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { KyckrApiError, KyckrHttpClient } from '../../kyckr-http.client';
import { Metrics } from '../../metrics';
import {
  KyckrBaseResponseShape,
  KyckrOrderDetailsSchema,
  McpEnvelopeShape,
} from '../../schemas/kyckr.schemas';

export const GetOrderInputSchema = z.object({
  orderId: z
    .union([z.string().trim().min(1), z.number().int()])
    .transform((v) => String(v))
    .describe(
      'Order id returned by `create_document_order.data.orderId` or seen in `list_orders.data.orders[].orderId`. May be a string or a number - both accepted; pass the value as-is.',
    ),
});

export type GetOrderInput = z.infer<typeof GetOrderInputSchema>;

const GetOrderEnvelopeSchema = z
  .object({
    ...KyckrBaseResponseShape,
    data: KyckrOrderDetailsSchema.optional(),
  })
  .loose();

export const GetOrderOutputSchema = z
  .object({
    ...McpEnvelopeShape,
    data: KyckrOrderDetailsSchema.optional(),
  })
  .loose();

export type GetOrderResult = z.infer<typeof GetOrderOutputSchema>;

@Injectable()
export class GetOrderQuery {
  private readonly logger = new Logger(GetOrderQuery.name);

  public constructor(
    private readonly kyckrClient: KyckrHttpClient,
    private readonly metrics: Metrics,
  ) {}

  @Span()
  public async run(input: GetOrderInput): Promise<GetOrderResult> {
    this.logger.debug({ orderId: input.orderId }, 'get_order: invoked');
    try {
      const raw = await this.kyckrClient.get<unknown>(
        `/orders/${encodeURIComponent(input.orderId)}`,
      );
      const response = GetOrderEnvelopeSchema.parse(raw);
      this.metrics.recordToolCall('get_order', 'success');
      this.metrics.recordCreditsConsumed('get_order', response.cost);
      this.logger.debug(
        { orderId: input.orderId, status: response.data?.status },
        'get_order: succeeded',
      );
      return { success: true, ...response };
    } catch (err) {
      if (err instanceof KyckrApiError) {
        this.logger.warn(
          {
            status: err.status,
            orderId: input.orderId,
            correlationId: err.correlationId,
            msg: err.message,
          },
          'get_order: Kyckr API rejected request',
        );
        this.metrics.recordToolCall('get_order', 'error');
        return {
          success: false,
          statusCode: err.status,
          message: err.message,
          correlationId: err.correlationId,
        };
      }
      throw err;
    }
  }
}
