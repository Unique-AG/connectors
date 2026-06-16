import { type Client, type PageCollection, PageIterator } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';

// Single home for the Graph pagination knobs. Every exhaustive collect pages in
// `GRAPH_PAGE_SIZE`-sized requests and is bounded by `GRAPH_MAX_ITEMS` so a
// pathological account cannot trigger an unbounded number of follow-up requests.
export const GRAPH_PAGE_SIZE = 50;

// Safety cap on the number of items collected/scanned across all pages. Replaces
// the previous "20 pages" cap; at the default page size this is functionally
// equivalent (~20 × 50) but expressed in items rather than pages.
export const GRAPH_MAX_ITEMS = 1000;

// Both helpers drive the Microsoft Graph SDK's `PageIterator` with the same
// `Client` the rest of the service uses, so every follow-up request flows
// through the existing middleware chain (auth, retry, metrics).
const logger = new Logger('GraphPagination');

// The helpers are deliberately schema-agnostic: they only page, returning the
// raw Graph items. Each call site validates the shape it expects once, with its
// own concrete Zod schema, after collection. Threading a generic Zod schema
// through these helpers is what we are avoiding — besides keeping pagination and
// validation as separate concerns, inferring through a `z.codec` schema (e.g.
// the transcript DTO) trips a TypeScript depth/heap blow-up.
type GraphRawItem = Record<string, unknown>;

/**
 * Exhaustively iterates every page of a Graph `@odata.nextLink` collection,
 * bounded by `maxItems`, returning the raw items. Use this whenever the call
 * site needs *all* items (list tools, name resolution) rather than a recent
 * window; validate the result with `z.array(schema).parse(items)`.
 *
 * `truncated` is `true` when the cap was hit before Graph ran out of pages
 * (`PageIterator.isComplete() === false`); a warning is logged so a silently
 * capped result is never mistaken for a complete one.
 */
export async function collectAllPages(
  client: Client,
  firstPage: PageCollection,
  opts: { maxItems?: number; label?: string } = {},
): Promise<{ items: unknown[]; truncated: boolean }> {
  const maxItems = opts.maxItems ?? GRAPH_MAX_ITEMS;
  const items: unknown[] = [];

  const iterator = new PageIterator(client, firstPage, (item) => {
    items.push(item);
    // Returning false stops the iterator; do so once the cap is reached so we
    // never page past it.
    return items.length < maxItems;
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

/**
 * Collects up to `limit` raw items passing `filter`, paging through intervening
 * noise (e.g. system messages Graph cannot filter server-side) as needed. A
 * `maxScanned` safety cap bounds how many raw items are inspected so a thread
 * that is almost entirely noise cannot page forever.
 *
 * `filter` runs against the raw Graph item (validate the returned slice with
 * `z.array(schema).parse(...)` at the call site).
 */
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
    // Stop once we have enough matches or we have scanned past the safety cap.
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
