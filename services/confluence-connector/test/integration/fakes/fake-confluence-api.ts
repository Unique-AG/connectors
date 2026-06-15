import assert from 'node:assert';
import { Readable } from 'node:stream';
import { clone } from 'remeda';
import {
  ConfluenceApiClient,
  type ConfluenceAttachment,
  type ConfluencePage,
  ContentType,
} from '../../../src/confluence-api';
import type { InstanceIdentifier } from '../../../src/confluence-api/confluence-api-client';
import { confluencePageSchema } from '../../../src/confluence-api/types/confluence-api.types';
import type {
  ScenarioAttachment,
  ScenarioConfluence,
  ScenarioPage,
  ScenarioSpace,
  ScenarioTenantConfig,
} from '../scenario/scenario.types';

/**
 * In-memory ConfluenceApiClient backed by a ScenarioConfluence document.
 *
 * Pages are filtered by the configured ingestSingleLabel / ingestAllLabel.
 * Descendants are resolved via the scenario's parentId tree.
 *
 * Every produced page goes through `confluencePageSchema.parse()` to fail loudly
 * if the fake drifts away from the production page shape.
 *
 * Also exposes a small mutation API (`addPage`, `removePage`, ...) for tests
 * that run in more than one step. To test a failure, a test mocks the method it
 * wants to fail (e.g. `vi.spyOn(fake, 'getPageById')`).
 */
export class FakeConfluenceApi extends ConfluenceApiClient {
  private readonly state: ScenarioConfluence;

  public constructor(
    private readonly tenant: ScenarioTenantConfig,
    state: ScenarioConfluence,
  ) {
    super();
    // Deep-copy the scenario state. The mutation API below (addPage, removePage,
    // splice, Object.assign, ...) writes to `this.state` in place, and scenarios
    // share default arrays/objects across tests, so without a copy one test
    // could mutate another's fixtures. `tenant` is never mutated, so it's left
    // as-is.
    //
    // Note: clone turns each attachment's `bytes` Buffer into a Uint8Array, so
    // `getAttachmentDownloadStream` re-wraps it in a Buffer before streaming.
    this.state = clone(state);
  }

  public async resolveInstanceIdentifier(): Promise<InstanceIdentifier> {
    if (this.tenant.instance.type === 'cloud') {
      return { type: 'cloud', id: this.tenant.instance.cloudId };
    }
    return { type: 'data-center', id: this.tenant.instance.baseUrl };
  }

  public async searchPagesByLabel(): Promise<ConfluencePage[]> {
    const labels = [this.tenant.ingestSingleLabel, this.tenant.ingestAllLabel];
    const matched = this.state.pages.filter((page) =>
      page.labels.some((label) => labels.includes(label)),
    );
    return matched.map((page) => this.toConfluencePage(page));
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const page = this.state.pages.find((p) => p.id === pageId);
    if (!page) {
      return null;
    }
    return this.toConfluencePage(page, { includeBody: true });
  }

  public async getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]> {
    const descendants = new Map<string, ScenarioPage>();
    const queue = [...rootIds];
    const visited = new Set<string>(rootIds);

    while (queue.length > 0) {
      const currentId = queue.shift();
      if (!currentId) {
        continue;
      }
      const children = this.state.pages.filter((p) => p.parentId === currentId);
      for (const child of children) {
        if (visited.has(child.id)) {
          continue;
        }
        visited.add(child.id);
        descendants.set(child.id, child);
        queue.push(child.id);
      }
    }

    return [...descendants.values()].map((page) => this.toConfluencePage(page));
  }

  public buildPageWebUrl(page: ConfluencePage): string {
    return `${this.tenant.instance.baseUrl}/wiki/spaces/${page.space.key}/pages/${page.id}`;
  }

  public buildAttachmentWebUrl(
    pageId: string,
    attachmentId: string,
    attachmentTitle: string,
  ): string {
    const numericId = attachmentId.replace(/^att/, '');
    const preview = encodeURIComponent(`/${pageId}/${numericId}/${attachmentTitle}`);
    return `${this.tenant.instance.baseUrl}/wiki/pages/viewpageattachments.action?pageId=${pageId}&preview=${preview}`;
  }

  public async getAttachmentDownloadStream(
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

  private getPageOrFail(pageId: string): ScenarioPage {
    const page = this.state.pages.find((p) => p.id === pageId);
    assert.ok(page, `Unknown page "${pageId}"`);
    return page;
  }

  private toConfluencePage(
    page: ScenarioPage,
    options: { includeBody?: boolean } = {},
  ): ConfluencePage {
    const space = this.getSpaceOrFail(page.spaceKey);
    const includeBody = options.includeBody ?? false;

    const attachments: ConfluenceAttachment[] = (page.attachments ?? []).map((attachment) => ({
      id: attachment.id,
      title: attachment.title,
      extensions: {
        mediaType: attachment.mediaType,
        fileSize: attachment.bytes.byteLength,
      },
      version: attachment.versionWhen ? { when: attachment.versionWhen } : undefined,
      _links: {
        download: `/download/attachments/${page.id}/${encodeURIComponent(attachment.title)}`,
      },
    }));

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
      ...(includeBody ? { body: { storage: { value: page.body } } } : {}),
      ...(this.tenant.attachmentsEnabled && attachments.length > 0
        ? {
            children: {
              attachment: {
                results: attachments,
                start: 0,
                limit: attachments.length,
                size: attachments.length,
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
