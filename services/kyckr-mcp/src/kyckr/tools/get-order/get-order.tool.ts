import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import { GetOrderInputSchema, GetOrderOutputSchema, GetOrderQuery } from './get-order.query';
import { META } from './get-order-tool.meta';

@Injectable()
export class GetOrderTool {
  public constructor(private readonly getOrderQuery: GetOrderQuery) {}

  @Tool({
    name: 'get_order',
    title: 'Get Order',
    description:
      'Retrieve a single Kyckr order by `orderId`. Free to call. Use to poll an order placed via `create_document_order` until `data.status` is `Success` (then use `data.links.document` / `data.links.data` to fetch the artifact) or `Failed`. Treat `statusCode: 410` as terminal — the order is no longer retrievable from Kyckr; do not retry.',
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
  ): Promise<z.infer<typeof GetOrderOutputSchema>> {
    return this.getOrderQuery.run(input);
  }
}
