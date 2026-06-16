import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  GetOrderInputSchema,
  GetOrderOutputSchema,
  GetOrderQuery,
  type GetOrderResult,
} from './get-order.query';
import { META } from './get-order-tool.meta';

@Injectable()
export class GetOrderTool {
  public constructor(private readonly getOrderQuery: GetOrderQuery) {}

  @Tool({
    name: 'get_order',
    title: 'Get Order',
    description:
      'Retrieve a single Kyckr order by `orderId`. Free to call. Use to poll an order placed via `create_document_order` until `data.status` is `Success` or `Failed`. When the status reaches `Success`, the structured JSON view of the document is fetched and inlined under `data.documentJson` - this IS the document; render it to the user as a readable summary. When no JSON projection exists for this filing, `data.documentJson` is absent and `details` notes that the document is PDF-only and PDF delivery is not yet supported - relay that message to the user, without referencing download URLs or order-internal links. Treat `statusCode: 410` as terminal - the order is no longer retrievable from Kyckr; do not retry.',
    parameters: GetOrderInputSchema,
    outputSchema: GetOrderOutputSchema,
    annotations: {
      title: 'Get Order',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async getOrder(
    input: z.infer<typeof GetOrderInputSchema>,
    _context: Context,
  ): Promise<GetOrderResult> {
    return this.getOrderQuery.run(input);
  }
}
