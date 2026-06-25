import assert from 'node:assert';
import { Readable } from 'node:stream';
import { clone } from 'remeda';
import { ConfluenceAuth } from '../../../src/auth/confluence-auth';
import type { ConfluenceConfig } from '../../../src/config';
import {
  type ConfluenceAttachment,
  type ConfluencePage,
  ContentType,
} from '../../../src/confluence-api';
import { CloudConfluenceApiClient } from '../../../src/confluence-api/cloud-api-client';
import { confluencePageSchema } from '../../../src/confluence-api/types/confluence-api.types';
import { createNoopMetrics } from '../../../src/metrics/__mocks__/noop-metrics';
import { RateLimitedHttpClient } from '../../../src/utils/rate-limited-http-client';
import type {
  ScenarioAttachment,
  ScenarioConfluence,
  ScenarioPage,
  ScenarioSpace,
} from '../scenario/scenario.types';

// Confluence Cloud inlines at most 25 attachments per page via
// expand=children.attachment; the client pages the rest from the v2 endpoint.
const INLINE_ATTACHMENT_LIMIT = 25;

class FakeConfluenceAuth extends ConfluenceAuth {
  public async acquireToken(): Promise<string> {
    return 'fake-token';
  }
}

/**
 * The real Cloud client driven by an in-memory Confluence instead of the network.
 *
 * Rather than reimplement the client's public methods, this overrides only the
 * two seams that touch the network: `makeAuthenticatedRequest` (returns the JSON
 * a Confluence search / v2 endpoint would) and `getAttachmentDownloadStream`.
 * Everything above that runs for real, so CQL handling, descendant fan-out, and
 * the >25-attachment pagination (`fetchMoreAttachments`) are exercised here.
 *
 * Search responses inline at most 25 attachments per page and mark the cap via
 * `size`/`limit`, exactly like Confluence; pages with more are completed by the
 * real client calling the v2 endpoint, which this fake also serves.
 *
 * Also exposes a small mutation API (`addPage`, `removePage`, ...) for tests
 * that run in more than one step. To test a failure, a test mocks the method it
 * wants to fail (e.g. `vi.spyOn(fake, 'getPageById')`).
 */
export class FakeConfluenceApi extends CloudConfluenceApiClient {
  private readonly state: ScenarioConfluence;

  public constructor(
    config: ConfluenceConfig,
    attachmentsEnabled: boolean,
    state: ScenarioConfluence,
  ) {
    assert.ok(config.instanceType === 'cloud', 'FakeConfluenceApi models the Cloud client only');
    super(config, new FakeConfluenceAuth(), new RateLimitedHttpClient(1000, createNoopMetrics()), {
      attachmentsEnabled,
    });
    // Deep-copy so the mutation API can't reach scenarios' shared default arrays.
    // `clone` turns each attachment's `bytes` Buffer into a Uint8Array, so the
    // download/v2 paths re-wrap it in a Buffer.
    this.state = clone(state);
  }

  protected override async makeAuthenticatedRequest(url: string): Promise<unknown> {
    const parsed = new URL(url);

    const v2Match = parsed.pathname.match(/\/wiki\/api\/v2\/pages\/([^/]+)\/attachments$/);
    if (v2Match?.[1]) {
      return this.attachmentsV2Response(v2Match[1]);
    }

    if (parsed.pathname.endsWith('/wiki/rest/api/content/search')) {
      return this.searchResponse(parsed.searchParams);
    }

    throw new Error(`FakeConfluenceApi received an unexpected request: ${url}`);
  }

  public override async getAttachmentDownloadStream(
    attachmentId: string,
    pageId: string,
    _downloadPath: string,
  ): Promise<Readable> {
    const page = this.state.pages.find((p) => p.id === pageId);
    const attachment = page?.attachments?.find((a) => a.id === attachmentId);
    assert.ok(attachment, `Attachment not found: pageId=${pageId} attachmentId=${attachmentId}`);
    return Readable.from(Buffer.from(attachment.bytes));
  }

  // ─── Mutation API (for multi-step / re-sync tests) ───────────────────────────

  public addSpace(space: ScenarioSpace): void {
    assert.ok(
      !this.state.spaces.some((s) => s.key === space.key),
      `Space "${space.key}" already exists`,
    );
    this.state.spaces.push(space);
  }

  public addPage(page: ScenarioPage): void {
    assert.ok(!this.state.pages.some((p) => p.id === page.id), `Page "${page.id}" already exists`);
    this.state.pages.push(page);
  }

  public removePage(pageId: string): void {
    const index = this.state.pages.findIndex((p) => p.id === pageId);
    assert.ok(index !== -1, `Cannot remove unknown page "${pageId}"`);
    this.state.pages.splice(index, 1);
  }

  public updatePage(pageId: string, updates: Partial<Omit<ScenarioPage, 'id'>>): void {
    const page = this.getPageOrFail(pageId);
    Object.assign(page, updates);
  }

  public bumpPageVersion(pageId: string, when: string): void {
    this.getPageOrFail(pageId).versionWhen = when;
  }

  public addAttachment(pageId: string, attachment: ScenarioAttachment): void {
    const page = this.getPageOrFail(pageId);
    page.attachments ??= [];
    assert.ok(
      !page.attachments.some((a) => a.id === attachment.id),
      `Attachment "${attachment.id}" already exists on page "${pageId}"`,
    );
    page.attachments.push(attachment);
  }

  public removeAttachment(pageId: string, attachmentId: string): void {
    const page = this.getPageOrFail(pageId);
    const index = page.attachments?.findIndex((a) => a.id === attachmentId) ?? -1;
    assert.ok(
      index !== -1,
      `Cannot remove unknown attachment "${attachmentId}" from page "${pageId}"`,
    );
    page.attachments?.splice(index, 1);
  }

  // ─── Request synthesis ───────────────────────────────────────────────────────

  private searchResponse(params: URLSearchParams): unknown {
    const cql = params.get('cql') ?? '';
    const expand = params.get('expand') ?? '';
    const includeBody = expand.includes('body.storage');
    const includeAttachments = expand.includes('children.attachment');
    const results = this.matchPages(cql).map((page) =>
      this.toConfluencePage(page, { includeBody, includeAttachments }),
    );
    return { results, _links: {} };
  }

  private matchPages(cql: string): ScenarioPage[] {
    const idMatch = cql.match(/^id=(.+)$/);
    if (idMatch?.[1]) {
      const page = this.state.pages.find((p) => p.id === idMatch[1]);
      return page ? [page] : [];
    }

    const ancestorMatch = cql.match(/ancestor IN \(([^)]+)\)/);
    if (ancestorMatch?.[1]) {
      const rootIds = ancestorMatch[1].split(',').map((id) => id.trim());
      return this.descendantsOf(rootIds);
    }

    const labels = [...cql.matchAll(/label="([^"]+)"/g)].map((m) => m[1]);
    return this.state.pages.filter((page) => page.labels.some((label) => labels.includes(label)));
  }

  private descendantsOf(rootIds: string[]): ScenarioPage[] {
    const found = new Map<string, ScenarioPage>();
    const queue = [...rootIds];
    const visited = new Set<string>(rootIds);

    while (queue.length > 0) {
      const currentId = queue.shift();
      if (!currentId) {
        continue;
      }
      for (const child of this.state.pages.filter((p) => p.parentId === currentId)) {
        if (visited.has(child.id)) {
          continue;
        }
        visited.add(child.id);
        found.set(child.id, child);
        queue.push(child.id);
      }
    }

    return [...found.values()];
  }

  private attachmentsV2Response(pageId: string): unknown {
    const page = this.state.pages.find((p) => p.id === pageId);
    const results = (page?.attachments ?? []).map((attachment) => ({
      id: attachment.id,
      title: attachment.title,
      mediaType: attachment.mediaType,
      fileSize: attachment.bytes.byteLength,
      downloadLink: `/download/${pageId}/${attachment.id}`,
      ...(attachment.versionWhen ? { version: { createdAt: attachment.versionWhen } } : {}),
    }));
    return { results, _links: {} };
  }

  private getPageOrFail(pageId: string): ScenarioPage {
    const page = this.state.pages.find((p) => p.id === pageId);
    assert.ok(page, `Unknown page "${pageId}"`);
    return page;
  }

  private toConfluencePage(
    page: ScenarioPage,
    options: { includeBody: boolean; includeAttachments: boolean },
  ): ConfluencePage {
    const space = this.getSpaceOrFail(page.spaceKey);
    const allAttachments = page.attachments ?? [];
    const inlined = allAttachments.slice(0, INLINE_ATTACHMENT_LIMIT).map(
      (attachment): ConfluenceAttachment => ({
        id: attachment.id,
        title: attachment.title,
        extensions: { mediaType: attachment.mediaType, fileSize: attachment.bytes.byteLength },
        version: attachment.versionWhen ? { when: attachment.versionWhen } : undefined,
        _links: {
          download: `/download/attachments/${page.id}/${encodeURIComponent(attachment.title)}`,
        },
      }),
    );

    const raw: ConfluencePage = {
      id: page.id,
      title: page.title,
      type: page.type ?? ContentType.PAGE,
      space: { id: space.id, key: space.key, name: space.name },
      version: { when: page.versionWhen },
      _links: { webui: `/spaces/${page.spaceKey}/pages/${page.id}` },
      metadata: {
        labels: { results: page.labels.map((name) => ({ name })) },
      },
      ...(options.includeBody ? { body: { storage: { value: page.body } } } : {}),
      ...(options.includeAttachments && allAttachments.length > 0
        ? {
            // Inline at most 25 and report the cap. When there are more, the real
            // client sees size >= limit and pages the rest from the v2 endpoint.
            children: {
              attachment: {
                results: inlined,
                size: inlined.length,
                limit: INLINE_ATTACHMENT_LIMIT,
              },
            },
          }
        : {}),
    };

    return confluencePageSchema.parse(raw);
  }

  private getSpaceOrFail(spaceKey: string): ScenarioSpace {
    const space = this.state.spaces.find((s) => s.key === spaceKey);
    assert.ok(
      space,
      `Scenario references unknown spaceKey "${spaceKey}". Add it to scenario.confluence.spaces.`,
    );
    return space;
  }
}
