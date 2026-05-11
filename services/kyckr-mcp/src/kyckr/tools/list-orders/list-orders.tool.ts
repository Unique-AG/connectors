import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  ListOrdersInputSchema,
  ListOrdersOutputSchema,
  ListOrdersQuery,
} from './list-orders.query';
import { META } from './list-orders-tool.meta';

@Injectable()
export class ListOrdersTool {
  public constructor(private readonly listOrdersQuery: ListOrdersQuery) {}

  @Tool({
    name: 'list_orders',
    title: 'List Orders',
    description:
      'List previously placed Kyckr orders. Free to call. Optional filters: `startDate` / `endDate` (ISO 8601), `isoCode` (jurisdiction). Orders are under `data.orders[]`; pagination metadata at `data.pageNumber` / `data.pageSize` / `data.totalCount`. Each entry has the same shape as `get_order.data` — `orderId`, `status`, `cost`, `companyDetails`, and `links` once completed. Use to reconcile when an `orderId` is not in context.',
    parameters: ListOrdersInputSchema,
    outputSchema: ListOrdersOutputSchema,
    annotations: {
      title: 'List Orders',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async listOrders(
    input: z.infer<typeof ListOrdersInputSchema>,
    _context: Context,
  ): Promise<z.infer<typeof ListOrdersOutputSchema>> {
    return this.listOrdersQuery.run(input);
  }
}
