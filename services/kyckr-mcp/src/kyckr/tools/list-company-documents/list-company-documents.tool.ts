import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import type * as z from 'zod';
import {
  ListCompanyDocumentsInputSchema,
  ListCompanyDocumentsOutputSchema,
  ListCompanyDocumentsQuery,
} from './list-company-documents.query';
import { META } from './list-company-documents-tool.meta';

@Injectable()
export class ListCompanyDocumentsTool {
  public constructor(private readonly listCompanyDocumentsQuery: ListCompanyDocumentsQuery) {}

  @Tool({
    name: 'list_company_documents',
    title: 'List Company Documents',
    description:
      'List official registry documents available to order for a company. The listing is free; only `create_document_order` consumes credits. Each entry includes a product `id` (use as `productId` when ordering), `name`, `category`, `documentDate`, expected `deliveryTimeMinutes`, and the credit `cost` of ordering. Paginate with `continuationKey` when the response includes one.',
    parameters: ListCompanyDocumentsInputSchema,
    outputSchema: ListCompanyDocumentsOutputSchema,
    annotations: {
      title: 'List Company Documents',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async listCompanyDocuments(
    input: z.infer<typeof ListCompanyDocumentsInputSchema>,
    _context: Context,
  ): Promise<z.infer<typeof ListCompanyDocumentsOutputSchema>> {
    return this.listCompanyDocumentsQuery.run(input);
  }
}
