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

interface FailureMap {
  searchPagesByLabel?: Error;
  getPageById: Map<string, Error>;
  getDescendantPages?: Error;
  getAttachmentDownloadStream: Map<string, Error>;
}

/**
 * In-memory ConfluenceApiClient backed by a ScenarioConfluence document.
 *
 * Pages are filtered by the configured ingestSingleLabel / ingestAllLabel.
 * Descendants are resolved via the scenario's parentId tree.
 *
 * Every produced page goes through `confluencePageSchema.parse()` to fail loudly
 * if the fake drifts away from the production page shape.
 *
 * Also exposes a small mutation API (`addPage`, `removePage`, ...) and
 * error-injection hooks (`failOn*`) for tests that drive multi-step or
 * failure-path scenarios.
 */
export class FakeConfluenceApi extends ConfluenceApiClient {
  private readonly failures: FailureMap = {
    getPageById: new Map(),
    getAttachmentDownloadStream: new Map(),
  };

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
    if (this.failures.searchPagesByLabel) {
      throw this.failures.searchPagesByLabel;
    }
    const labels = [this.tenant.ingestSingleLabel, this.tenant.ingestAllLabel];
    const matched = this.state.pages.filter((page) =>
      page.labels.some((label) => labels.includes(label)),
    );
    return matched.map((page) => this.toConfluencePage(page));
  }

  public async getPageById(pageId: string): Promise<ConfluencePage | null> {
    const failure = this.failures.getPageById.get(pageId);
    if (failure) {
      throw failure;
    }
    const page = this.state.pages.find((p) => p.id === pageId);
    if (!page) {
      return null;
    }
    return this.toConfluencePage(page, { includeBody: true });
  }

  public async getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]> {
    if (this.failures.getDescendantPages) {
      throw this.failures.getDescendantPages;
    }
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
    const failure = this.failures.getAttachmentDownloadStream.get(attachmentId);
    if (failure) {
      throw failure;
    }
    const page = this.state.pages.find((p) => p.id === pageId);
    const attachment = page?.attachments?.find((a) => a.id === attachmentId);
    if (!attachment) {
      throw new Error(`Attachment not found: pageId=${pageId} attachmentId=${attachmentId}`);
    }
    return Readable.from(Buffer.from(attachment.bytes));
  }

  // ─── Mutation API (for multi-step / re-sync tests) ───────────────────────────

  public addSpace(space: ScenarioSpace): void {
    if (this.state.spaces.some((s) => s.key === space.key)) {
      throw new Error(`Space "${space.key}" already exists`);
    }
    this.state.spaces.push(space);
  }

  public addPage(page: ScenarioPage): void {
    if (this.state.pages.some((p) => p.id === page.id)) {
      throw new Error(`Page "${page.id}" already exists`);
    }
    this.state.pages.push(page);
  }

  public removePage(pageId: string): void {
    const index = this.state.pages.findIndex((p) => p.id === pageId);
    if (index === -1) {
      throw new Error(`Cannot remove unknown page "${pageId}"`);
    }
    this.state.pages.splice(index, 1);
  }

  public updatePage(pageId: string, updates: Partial<Omit<ScenarioPage, 'id'>>): void {
    const page = this.requirePage(pageId);
    Object.assign(page, updates);
  }

  public bumpPageVersion(pageId: string, when: string): void {
    this.requirePage(pageId).versionWhen = when;
  }

  public addAttachment(pageId: string, attachment: ScenarioAttachment): void {
    const page = this.requirePage(pageId);
    page.attachments ??= [];
    if (page.attachments.some((a) => a.id === attachment.id)) {
      throw new Error(`Attachment "${attachment.id}" already exists on page "${pageId}"`);
    }
    page.attachments.push(attachment);
  }

  public removeAttachment(pageId: string, attachmentId: string): void {
    const page = this.requirePage(pageId);
    const index = page.attachments?.findIndex((a) => a.id === attachmentId) ?? -1;
    if (index === -1) {
      throw new Error(`Cannot remove unknown attachment "${attachmentId}" from page "${pageId}"`);
    }
    page.attachments?.splice(index, 1);
  }

  // ─── Failure-injection hooks ─────────────────────────────────────────────────

  public failOnSearchPagesByLabel(error: Error): void {
    this.failures.searchPagesByLabel = error;
  }

  public failOnGetPageById(pageId: string, error: Error): void {
    this.failures.getPageById.set(pageId, error);
  }

  public failOnGetDescendantPages(error: Error): void {
    this.failures.getDescendantPages = error;
  }

  public failOnGetAttachmentDownloadStream(attachmentId: string, error: Error): void {
    this.failures.getAttachmentDownloadStream.set(attachmentId, error);
  }

  public clearFailures(): void {
    this.failures.searchPagesByLabel = undefined;
    this.failures.getDescendantPages = undefined;
    this.failures.getPageById.clear();
    this.failures.getAttachmentDownloadStream.clear();
  }

  private requirePage(pageId: string): ScenarioPage {
    const page = this.state.pages.find((p) => p.id === pageId);
    if (!page) {
      throw new Error(`Unknown page "${pageId}"`);
    }
    return page;
  }

  private toConfluencePage(
    page: ScenarioPage,
    options: { includeBody?: boolean } = {},
  ): ConfluencePage {
    const space = this.requireSpace(page.spaceKey);
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

  private requireSpace(spaceKey: string): ScenarioSpace {
    const space = this.state.spaces.find((s) => s.key === spaceKey);
    if (!space) {
      throw new Error(
        `Scenario references unknown spaceKey "${spaceKey}". Add it to scenario.confluence.spaces.`,
      );
    }
    return space;
  }
}
