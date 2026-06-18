import { type Client, type PageCollection, PageIterator } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';

export const GRAPH_PAGE_SIZE = 50; // default $top for exhaustive collects
export const GRAPH_MAX_ITEMS = 1000; // safety cap on items collected/scanned

const logger = new Logger('GraphPagination');

type GraphRawItem = Record<string, unknown>;

// Page through every `@odata.nextLink` (up to maxItems) and return the raw items;
// validate them at the call site. `truncated` is true when the cap was hit first.
export async function collectAllPages(
  client: Client,
  firstPage: PageCollection,
  opts: { maxItems?: number; label?: string } = {},
): Promise<{ items: unknown[]; truncated: boolean }> {
  const maxItems = opts.maxItems ?? GRAPH_MAX_ITEMS;
  const items: unknown[] = [];

  const iterator = new PageIterator(client, firstPage, (item) => {
    items.push(item);
    return items.length < maxItems; // false stops the iterator at the cap
  });
  await iterator.iterate();

  const truncated = !iterator.isComplete();
  if (truncated) {
    logger.warn(
      { label: opts.label, maxItems, collected: items.length },
      'Graph pagination hit the item cap; result is truncated',
    );
  }

  return { items, truncated };
}

// Collect up to `limit` raw items passing `filter`, paging through noise (e.g.
// system messages) up to a `maxScanned` cap. Validate the slice at the call site.
export async function collectUntil(
  client: Client,
  firstPage: PageCollection,
  opts: { limit: number; filter?: (item: GraphRawItem) => boolean; maxScanned?: number },
): Promise<unknown[]> {
  const maxScanned = opts.maxScanned ?? GRAPH_MAX_ITEMS;
  const collected: unknown[] = [];
  let scanned = 0;

  const iterator = new PageIterator(client, firstPage, (item: GraphRawItem) => {
    scanned++;
    if (!opts.filter || opts.filter(item)) {
      collected.push(item);
    }
    return collected.length < opts.limit && scanned < maxScanned;
  });
  await iterator.iterate();

  if (collected.length < opts.limit && !iterator.isComplete()) {
    logger.warn(
      { limit: opts.limit, scanned, collected: collected.length, maxScanned },
      'Graph pagination hit the scan cap before reaching the requested limit',
    );
  }

  return collected.slice(0, opts.limit);
}
