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

// Shared by both fetchPageAttachmentsByTitle implementations so the only
// per-platform difference is URL construction and attachment pagination.
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

  // Resolves a page in the given space by exact title and returns its attachments.
  // Used by the page image inliner to fulfil cross-page <ri:attachment> references.
  // Returns null when the page is not found or when attachment ingestion is disabled.
  public abstract fetchPageAttachmentsByTitle(
    spaceKey: string,
    title: string,
  ): Promise<PageAttachmentLookupResult | null>;
}
