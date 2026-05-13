import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  CreateDocumentOrderInputSchema,
  CreateDocumentOrderOutputSchema,
  CreateDocumentOrderQuery,
  type CreateDocumentOrderResult,
} from './create-document-order.query';
import { META } from './create-document-order-tool.meta';

@Injectable()
export class CreateDocumentOrderTool {
  public constructor(private readonly createDocumentOrderQuery: CreateDocumentOrderQuery) {}

  @Tool({
    name: 'create_document_order',
    title: 'Order Document',
    description:
      'Place a paid Kyckr order for an official registry document. The only write-side tool here: every successful call spends Kyckr credits and creates a real registry order. Required: `kyckrId` (from `search_companies`) and `productId` (from `list_company_documents`). Call directly once the user has named or chosen a specific filing - do not ask for a separate confirmation step (cost is already known from `list_company_documents`). Returns `data.orderId` and `data.status`. When the registry completes the order immediately (`status: "Success"`), the structured JSON view of the document is fetched and inlined under `data.documentJson` - this IS the document; render it to the user as a readable summary. When no JSON projection exists, the response attaches the official PDF as an embedded resource block; summarise the PDF content directly to the user. Never reference download URLs or order-internal links; only ever speak about document contents. When `status: "Pending"` (most jurisdictions), poll `get_order(data.orderId)` until `data.documentJson` (or the attached PDF resource) is available or `status` is `Failed`.',
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
  ): Promise<CreateDocumentOrderResult> {
    return this.createDocumentOrderQuery.run(input);
  }
}
