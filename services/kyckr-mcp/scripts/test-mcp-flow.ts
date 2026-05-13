/**
 * Manual end-to-end check of the kyckr-mcp tool flow against a running server.
 * Not part of the test suite - run with:
 *   pnpm --filter @unique-ag/kyckr-mcp exec tsx scripts/test-mcp-flow.ts
 *
 * Requires the dev server running on http://localhost:9542 with MCP_API_KEY=my-demo-api-key.
 */
import { setTimeout as wait } from 'node:timers/promises';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const BASE_URL = process.env.KYCKR_MCP_URL ?? 'http://localhost:9542';
const API_KEY = process.env.MCP_API_KEY ?? 'my-demo-api-key';
const ENDPOINT = `${BASE_URL}/${API_KEY}/mcp`;

type ContentBlock = {
  type: string;
  text?: string;
  resource?: { uri?: string; mimeType?: string; blob?: string };
};
type ToolCallPayload = { content: ContentBlock[]; structuredContent?: unknown };

function logHeading(title: string) {
  console.log(`\n=== ${title} ===`);
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function structured<T = unknown>(result: ToolCallPayload): T {
  if (!result.structuredContent) {
    throw new Error(`No structuredContent on tool result:\n${pretty(result)}`);
  }
  return result.structuredContent as T;
}

function pdfResourceSummary(result: ToolCallPayload):
  | { uri: string; mimeType: string; blobLength: number }
  | undefined {
  const block = result.content.find(
    (c) => c.type === 'resource' && c.resource?.mimeType === 'application/pdf',
  );
  if (!block?.resource?.blob) return undefined;
  return {
    uri: block.resource.uri ?? '(no uri)',
    mimeType: block.resource.mimeType ?? '(no mime)',
    blobLength: block.resource.blob.length,
  };
}

function linksField(structuredData: { data?: unknown } | undefined): unknown {
  const data = structuredData?.data as Record<string, unknown> | undefined;
  return data && 'links' in data ? data.links : undefined;
}

async function main() {
  const transport = new StreamableHTTPClientTransport(new URL(ENDPOINT));
  const client = new Client({ name: 'kyckr-mcp-flow-tester', version: '1.0.0' });
  await client.connect(transport);
  console.log(`Connected to ${ENDPOINT}`);

  logHeading('1. List tools');
  const tools = await client.listTools();
  console.log(tools.tools.map((t) => `- ${t.name}`).join('\n'));

  type DocEntry = {
    id?: string;
    name?: string;
    documentFormat?: string[];
    cost?: { value?: number };
  };

  logHeading('A. list_orders (look for an already-completed order to validate get_order auto-fetch)');
  const orders = structured<{
    data?: { orders?: Array<{ orderId?: string | number; status?: string; productDetails?: { productName?: string }; companyDetails?: { kyckrId?: string } }> };
  }>(await client.callTool({ name: 'list_orders', arguments: {} }));
  const completedOrder = orders.data?.orders?.find((o) => o.status === 'Success');
  if (completedOrder?.orderId !== undefined) {
    logHeading('B. get_order on a historical Success order (exercises document-body delivery on polling)');
    const raw = await client.callTool({
      name: 'get_order',
      arguments: { orderId: String(completedOrder.orderId) },
    });
    const fetched = structured<{
      success: boolean;
      details?: string;
      data?: { status?: string; documentJson?: unknown };
    }>(raw as ToolCallPayload);
    console.log(pretty(fetched));
    console.log({
      historicalOrderId: completedOrder.orderId,
      productName: completedOrder.productDetails?.productName,
      finalStatus: fetched.data?.status,
      hasDocumentJson: fetched.data?.documentJson !== undefined,
      documentJsonTopLevelKeys: fetched.data?.documentJson
        ? Object.keys(fetched.data.documentJson as Record<string, unknown>)
        : undefined,
      pdfResource: pdfResourceSummary(raw as ToolCallPayload),
      linksExposed: linksField(fetched),
      detail: fetched.details,
    });
  } else {
    console.log('No historical Success orders found.');
  }

  logHeading('C. search_companies (UK by companyNumber - sandbox name search returns many hits)');
  const search = structured<{
    data?: Array<{ id?: string; companyName?: string; companyNumber?: string }>;
  }>(
    await client.callTool({
      name: 'search_companies',
      arguments: { companyNumber: '00000006', isoCode: 'GB' },
    }),
  );
  const matches = search.data ?? [];
  console.log(`-> ${matches.length} match(es) returned. First 5:`);
  for (const m of matches.slice(0, 5)) console.log(`   ${m.id} ${m.companyNumber} ${m.companyName}`);
  const kyckrId = matches[0]?.id;
  if (!kyckrId) throw new Error('No company returned from search');
  console.log(`-> picked kyckrId=${kyckrId}`);

  logHeading('D. list_company_documents');
  const docs = structured<{ data?: DocEntry[] }>(
    await client.callTool({ name: 'list_company_documents', arguments: { kyckrId } }),
  );
  const allDocs = docs.data ?? [];
  console.log(`-> ${allDocs.length} doc(s)`);
  // `documentFormat` only describes the registry-served file format; Kyckr may
  // still expose a JSON projection on the download endpoint for any document,
  // so pick the first available filing without filtering on format.
  const document = allDocs[0];
  if (!document?.id) throw new Error('No document available to order');
  console.log(`-> picked productId=${document.id} (${document.name}) formats=${pretty(document.documentFormat)}`);
  const productId = document.id;

  logHeading('4. create_document_order');
  const createdRaw = (await client.callTool({
    name: 'create_document_order',
    arguments: { kyckrId, productId },
  })) as ToolCallPayload;
  const created = structured<{
    success: boolean;
    details?: string;
    data?: { orderId?: string | number; status?: string; documentJson?: unknown };
  }>(createdRaw);
  console.log(pretty(created));
  console.log({
    pdfResource: pdfResourceSummary(createdRaw),
    linksExposed: linksField(created),
  });

  const orderId = created.data?.orderId;
  const initialStatus = created.data?.status;
  const documentJsonAtCreate = created.data?.documentJson;
  if (orderId === undefined) {
    throw new Error('No orderId returned from create_document_order');
  }

  if (initialStatus === 'Success' && documentJsonAtCreate !== undefined) {
    logHeading('-> Order completed immediately, documentJson inlined on create_document_order');
  } else if (initialStatus === 'Success' && documentJsonAtCreate === undefined) {
    logHeading(`-> Order Success but no JSON form. details="${created.details ?? ''}"`);
  } else {
    logHeading(`-> Order ${initialStatus}, will poll get_order`);
  }

  logHeading('5. get_order (poll)');
  const maxAttempts = 3;
  let lastFetched: { data?: { status?: string; documentJson?: unknown }; details?: string } | undefined;
  let lastRaw: ToolCallPayload | undefined;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    console.log(`\n--- attempt ${attempt}/${maxAttempts} ---`);
    const raw = (await client.callTool({
      name: 'get_order',
      arguments: { orderId: String(orderId) },
    })) as ToolCallPayload;
    const fetched = structured<{
      success: boolean;
      details?: string;
      data?: { status?: string; documentJson?: unknown };
    }>(raw);
    console.log(pretty(fetched));
    lastFetched = fetched;
    lastRaw = raw;
    const status = fetched.data?.status;
    if (status === 'Success' || status === 'Failed') {
      break;
    }
    if (attempt < maxAttempts) {
      console.log('still Pending, waiting 10s...');
      await wait(10_000);
    }
  }

  logHeading('Final summary');
  console.log({
    orderId,
    initialStatus,
    finalStatus: lastFetched?.data?.status,
    hasDocumentJson: lastFetched?.data?.documentJson !== undefined,
    pdfResource: lastRaw ? pdfResourceSummary(lastRaw) : undefined,
    linksExposed: linksField(lastFetched),
    detail: lastFetched?.details,
  });

  await client.close();
}

main().catch((err) => {
  console.error('flow tester failed:', err);
  process.exit(1);
});
