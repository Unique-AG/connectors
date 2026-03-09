import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import {
  type DriveItemDelta,
  type DrivePermission,
  DrivePermissionSchema,
  type GroupMember,
  GroupMemberSchema,
  type Notebook,
  NotebookSchema,
  type Page,
  PageSchema,
  type Section,
  type SectionGroup,
  SectionGroupSchema,
  SectionSchema,
} from './onenote.types';

@Injectable()
export class OneNoteGraphService {
  private readonly logger = new Logger(OneNoteGraphService.name);

  @Span()
  public async listNotebooks(client: Client): Promise<Notebook[]> {
    const response = await client
      .api('/me/onenote/notebooks')
      .select('id,displayName,createdDateTime,lastModifiedDateTime,isShared,userRole,links')
      .get();

    return (response.value as unknown[]).map((n) => NotebookSchema.parse(n));
  }

  @Span()
  public async listSections(client: Client, notebookId: string): Promise<Section[]> {
    const response = await client
      .api(`/me/onenote/notebooks/${notebookId}/sections`)
      .select('id,displayName,createdDateTime,lastModifiedDateTime,isDefault,links')
      .get();

    return (response.value as unknown[]).map((s) => SectionSchema.parse(s));
  }

  @Span()
  public async listSectionGroups(client: Client, notebookId: string): Promise<SectionGroup[]> {
    const response = await client
      .api(`/me/onenote/notebooks/${notebookId}/sectionGroups`)
      .select('id,displayName,createdDateTime,lastModifiedDateTime')
      .get();

    return (response.value as unknown[]).map((sg) => SectionGroupSchema.parse(sg));
  }

  @Span()
  public async listSectionsInGroup(client: Client, sectionGroupId: string): Promise<Section[]> {
    const response = await client
      .api(`/me/onenote/sectionGroups/${sectionGroupId}/sections`)
      .select('id,displayName,createdDateTime,lastModifiedDateTime,isDefault,links')
      .get();

    return (response.value as unknown[]).map((s) => SectionSchema.parse(s));
  }

  @Span()
  public async listPages(client: Client, sectionId: string): Promise<Page[]> {
    const pages: Page[] = [];
    let nextLink: string | undefined;

    const initialResponse = await client
      .api(`/me/onenote/sections/${sectionId}/pages`)
      .select('id,title,createdDateTime,lastModifiedDateTime,contentUrl,links')
      .orderby('createdDateTime')
      .top(100)
      .get();

    pages.push(...(initialResponse.value as unknown[]).map((p) => PageSchema.parse(p)));
    nextLink = initialResponse['@odata.nextLink'];

    while (nextLink) {
      const response = await client.api(nextLink).get();
      pages.push(...(response.value as unknown[]).map((p) => PageSchema.parse(p)));
      nextLink = response['@odata.nextLink'];
    }

    return pages;
  }

  @Span()
  public async getPageContent(client: Client, pageId: string): Promise<string> {
    const stream = await client.api(`/me/onenote/pages/${pageId}/content`).getStream();

    const chunks: Buffer[] = [];
    const reader = stream.getReader();
    let done = false;
    while (!done) {
      const result = await reader.read();
      done = result.done;
      if (result.value) chunks.push(Buffer.from(result.value));
    }
    return Buffer.concat(chunks).toString('utf-8');
  }

  @Span()
  public async getNotebookDriveItem(
    client: Client,
    notebookId: string,
  ): Promise<{ driveId: string; itemId: string } | null> {
    try {
      const response = await client
        .api(`/me/onenote/notebooks/${notebookId}`)
        .select('id')
        .expand('parentNotebook')
        .get();

      // Notebooks don't expose driveId directly; use the self URL to extract drive info
      // Alternative: search drive items for the notebook by name
      const driveItem = await client
        .api("/me/drive/root/search(q='.onetoc2')")
        .select('id,name,parentReference')
        .filter(`name eq '${response.displayName}.onetoc2' or name eq 'Open Notebook.onetoc2'`)
        .top(1)
        .get();

      const item = driveItem?.value?.[0];
      if (item?.parentReference?.driveId && item?.id) {
        return { driveId: item.parentReference.driveId, itemId: item.id };
      }

      return null;
    } catch (error) {
      this.logger.warn({ error, notebookId }, 'Failed to resolve notebook drive item');
      return null;
    }
  }

  @Span()
  public async getNotebookPermissions(
    client: Client,
    driveId: string,
    itemId: string,
  ): Promise<DrivePermission[]> {
    try {
      const response = await client.api(`/drives/${driveId}/items/${itemId}/permissions`).get();

      return (response.value as unknown[]).map((p) => DrivePermissionSchema.parse(p));
    } catch (error) {
      this.logger.warn({ error, driveId, itemId }, 'Failed to fetch notebook permissions');
      return [];
    }
  }

  @Span()
  public async getGroupMembers(client: Client, groupId: string): Promise<GroupMember[]> {
    try {
      const response = await client.api(`/groups/${groupId}/members`).get();
      return (response.value as unknown[]).map((m) => GroupMemberSchema.parse(m));
    } catch (error) {
      this.logger.warn({ error, groupId }, 'Failed to fetch group members');
      return [];
    }
  }

  @Span()
  public async getDelta(
    client: Client,
    deltaLink?: string,
  ): Promise<{ items: DriveItemDelta[]; nextDeltaLink: string }> {
    const items: DriveItemDelta[] = [];
    let url = deltaLink ?? '/me/drive/root/delta';

    let hasMore = true;
    while (hasMore) {
      const response = await client.api(url).get();

      if (response.value) {
        for (const item of response.value) {
          items.push(item as DriveItemDelta);
        }
      }

      if (response['@odata.nextLink']) {
        url = response['@odata.nextLink'];
      } else {
        hasMore = false;
        return { items, nextDeltaLink: response['@odata.deltaLink'] ?? '' };
      }
    }

    return { items, nextDeltaLink: '' };
  }

  @Span()
  public async createNotebook(client: Client, displayName: string): Promise<Notebook> {
    const response = await client.api('/me/onenote/notebooks').post({ displayName });

    return NotebookSchema.parse(response);
  }

  @Span()
  public async createSection(
    client: Client,
    notebookId: string,
    displayName: string,
  ): Promise<Section> {
    const response = await client
      .api(`/me/onenote/notebooks/${notebookId}/sections`)
      .post({ displayName });

    return SectionSchema.parse(response);
  }

  @Span()
  public async createPage(
    client: Client,
    sectionId: string,
    title: string,
    contentHtml: string,
  ): Promise<Page> {
    const html = `<!DOCTYPE html>
<html>
  <head><title>${title}</title></head>
  <body>${contentHtml}</body>
</html>`;

    const response = await client
      .api(`/me/onenote/sections/${sectionId}/pages`)
      .header('Content-Type', 'application/xhtml+xml')
      .post(html);

    return PageSchema.parse(response);
  }

  @Span()
  public async updatePage(
    client: Client,
    pageId: string,
    changes: Array<{ target: string; action: string; position?: string; content: string }>,
  ): Promise<void> {
    await client
      .api(`/me/onenote/pages/${pageId}/content`)
      .header('Content-Type', 'application/json')
      .patch(changes);
  }
}
