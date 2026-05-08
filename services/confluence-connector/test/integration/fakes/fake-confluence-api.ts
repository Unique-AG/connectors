import { Readable } from 'node:stream';
import {
  ConfluenceApiClient,
  type ConfluenceAttachment,
  type ConfluencePage,
  ContentType,
} from '../../../src/confluence-api';
import type { InstanceIdentifier } from '../../../src/confluence-api/confluence-api-client';
import { confluencePageSchema } from '../../../src/confluence-api/types/confluence-api.types';
import type {
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
 */
export class FakeConfluenceApi extends ConfluenceApiClient {
  public constructor(
    private readonly tenant: ScenarioTenantConfig,
    private readonly state: ScenarioConfluence,
  ) {
    super();
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
    if (!attachment) {
      throw new Error(`Attachment not found: pageId=${pageId} attachmentId=${attachmentId}`);
    }
    return Readable.from(attachment.bytes);
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
      type: ContentType.PAGE,
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
