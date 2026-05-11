import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  CreateDocumentOrderInputSchema,
  CreateDocumentOrderOutputSchema,
  CreateDocumentOrderQuery,
} from './create-document-order.query';
import { META } from './create-document-order-tool.meta';

@Injectable()
export class CreateDocumentOrderTool {
  public constructor(private readonly createDocumentOrderQuery: CreateDocumentOrderQuery) {}

  @Tool({
    name: 'create_document_order',
    title: 'Order Document',
    description:
      'Place a paid Kyckr order for an official registry document. The only write-side tool here: every successful call spends Kyckr credits and creates a real registry order. Required: `kyckrId` (from `search_companies`) and `productId` (from `list_company_documents`). Before calling, show the user the document `name` and `cost` from `list_company_documents` and obtain explicit confirmation. On success returns `data.orderId` and `data.status` — most jurisdictions return `status: "Pending"`, so poll `get_order(data.orderId)` until `Success` (download links populated) or `Failed`.',
    parameters: CreateDocumentOrderInputSchema,
    outputSchema: CreateDocumentOrderOutputSchema,
    annotations: {
      title: 'Order Document',
      // Creates a real registry order on Kyckr's side and triggers a credit charge.
      readOnlyHint: false,
      // Not destructive: the order is additive, no existing data is mutated or lost.
      destructiveHint: false,
      // Each call places a new order and spends credits. Never advertise idempotency.
      idempotentHint: false,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async createDocumentOrder(
    input: z.infer<typeof CreateDocumentOrderInputSchema>,
    _context: Context,
  ): Promise<z.infer<typeof CreateDocumentOrderOutputSchema>> {
    return this.createDocumentOrderQuery.run(input);
  }
}
