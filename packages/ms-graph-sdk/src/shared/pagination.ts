import z from 'zod/v4';
import { ODataDeltaCollection } from './odata';

export interface GraphPage<T> {
  readonly value: T[];
  readonly nextLink: string | undefined;
  readonly deltaLink: string | undefined;
  readonly count: number | undefined;
}

export interface DeltaPage<T> extends GraphPage<T> {
  readonly isTerminal: boolean;
}

export class GraphPagedResponse<T> implements AsyncIterable<T> {
  public constructor(
    private readonly fetchFn: typeof globalThis.fetch,
    private readonly initialUrl: string,
    private readonly itemSchema: z.ZodType<T>,
    private readonly init?: RequestInit,
  ) {}

  private async fetchPage(url: string): Promise<GraphPage<T>> {
    const schema = ODataDeltaCollection(this.itemSchema);
    const response = await this.fetchFn(url, this.init);
    const raw: unknown = await response.json();
    const parsed = schema.parse(raw);
    return {
      value: parsed.value,
      nextLink: parsed['@odata.nextLink'],
      deltaLink: parsed['@odata.deltaLink'],
      count: parsed['@odata.count'],
    };
  }

  public async *[Symbol.asyncIterator](): AsyncIterator<T> {
    let page = await this.fetchPage(this.initialUrl);
    yield* page.value;
    while (page.nextLink) {
      page = await this.fetchPage(page.nextLink);
      yield* page.value;
    }
  }

  public async *pages(): AsyncGenerator<GraphPage<T>> {
    let page = await this.fetchPage(this.initialUrl);
    yield page;
    while (page.nextLink) {
      page = await this.fetchPage(page.nextLink);
      yield page;
    }
  }

  public async toArray(): Promise<T[]> {
    const items: T[] = [];
    for await (const item of this) items.push(item);
    return items;
  }

  public async first(): Promise<GraphPage<T>> {
    return this.fetchPage(this.initialUrl);
  }
}

export class DeltaResponse<T> {
  public constructor(
    private readonly fetchFn: typeof globalThis.fetch,
    private readonly initialUrl: string,
    private readonly itemSchema: z.ZodType<T>,
    private readonly init?: RequestInit,
  ) {}

  private async fetchPage(url: string): Promise<DeltaPage<T>> {
    const schema = ODataDeltaCollection(this.itemSchema);
    const response = await this.fetchFn(url, this.init);
    const raw: unknown = await response.json();
    const parsed = schema.parse(raw);
    return {
      value: parsed.value,
      nextLink: parsed['@odata.nextLink'],
      deltaLink: parsed['@odata.deltaLink'],
      count: parsed['@odata.count'],
      isTerminal: !!parsed['@odata.deltaLink'] && !parsed['@odata.nextLink'],
    };
  }

  public async *pages(): AsyncGenerator<DeltaPage<T>> {
    let page = await this.fetchPage(this.initialUrl);
    yield page;
    while (page.nextLink) {
      page = await this.fetchPage(page.nextLink);
      yield page;
    }
  }

  public async *items(): AsyncGenerator<T> {
    for await (const page of this.pages()) {
      yield* page.value;
    }
  }

  public async drain(): Promise<{ items: T[]; deltaLink: string | null }> {
    const items: T[] = [];
    let deltaLink: string | null = null;
    for await (const page of this.pages()) {
      items.push(...page.value);
      if (page.deltaLink) deltaLink = page.deltaLink;
    }
    return { items, deltaLink };
  }
}

export function paginate<T>(
  fetchFn: typeof globalThis.fetch,
  initialUrl: string,
  itemSchema: z.ZodType<T>,
  init?: RequestInit,
): GraphPagedResponse<T> {
  return new GraphPagedResponse(fetchFn, initialUrl, itemSchema, init);
}

export function paginateDelta<T>(
  fetchFn: typeof globalThis.fetch,
  initialUrl: string,
  itemSchema: z.ZodType<T>,
  init?: RequestInit,
): DeltaResponse<T> {
  return new DeltaResponse(fetchFn, initialUrl, itemSchema, init);
}
