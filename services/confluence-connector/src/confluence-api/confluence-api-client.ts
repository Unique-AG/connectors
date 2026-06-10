import type { Readable } from 'node:stream';
import type { ConfluenceAttachment, ConfluencePage } from './types/confluence-api.types';

export interface InstanceIdentifier {
  type: 'cloud' | 'data-center';
  id: string;
}

export interface ApiClientOptions {
  attachmentsEnabled: boolean;
}

export interface PageAttachmentLookupResult {
  pageId: string;
  attachments: ConfluenceAttachment[];
}

export function buildPageAttachmentLookupResult(page: ConfluencePage): PageAttachmentLookupResult {
  return {
    pageId: page.id,
    attachments: page.children?.attachment?.results ?? [],
  };
}

export abstract class ConfluenceApiClient {
  public abstract resolveInstanceIdentifier(): Promise<InstanceIdentifier>;

  public abstract searchPagesByLabel(): Promise<ConfluencePage[]>;

  public abstract getPageById(pageId: string): Promise<ConfluencePage | null>;

  public abstract getDescendantPages(rootIds: string[]): Promise<ConfluencePage[]>;

  public abstract buildPageWebUrl(page: ConfluencePage): string;

  public abstract buildAttachmentWebUrl(
    pageId: string,
    attachmentId: string,
    attachmentTitle: string,
  ): string;

  public abstract getAttachmentDownloadStream(
    attachmentId: string,
    pageId: string,
    downloadPath: string,
  ): Promise<Readable>;

  // Page titles are unique within a space, so (spaceKey, pageTitle) identifies a single page.
  public abstract fetchAttachmentsByPageTitle(
    spaceKey: string,
    pageTitle: string,
  ): Promise<PageAttachmentLookupResult | null>;
}
