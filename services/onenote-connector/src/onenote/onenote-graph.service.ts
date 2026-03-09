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
      const notebook = await client
        .api(`/me/onenote/notebooks/${notebookId}`)
        .select('id,displayName')
        .get();

      const notebookName = notebook.displayName as string;
      const searchResults = await client
        .api(`/me/drive/root/search(q='${this.escapeODataString(notebookName)}')`)
        .select('id,name,parentReference,package')
        .get();

      type DriveSearchItem = {
        id: string;
        name?: string;
        parentReference?: { driveId?: string; id?: string };
        package?: { type?: string };
      };
      const items = searchResults?.value as DriveSearchItem[] | undefined;
      if (!items?.length) return null;

      const notebookFolder = items.find(
        (item) => item.package?.type === 'oneNote' && item.name === notebookName,
      );
      if (notebookFolder?.parentReference?.driveId) {
        return { driveId: notebookFolder.parentReference.driveId, itemId: notebookFolder.id };
      }

      const tocFile = items.find((item) => item.name === `${notebookName}.onetoc2`);
      if (tocFile?.parentReference?.driveId && tocFile?.parentReference?.id) {
        return { driveId: tocFile.parentReference.driveId, itemId: tocFile.parentReference.id };
      }

      return null;
    } catch (error) {
      this.logger.warn({ error, notebookId }, 'Failed to resolve notebook drive item');
      return null;
    }
  }

  private escapeODataString(value: string): string {
    return encodeURIComponent(value)
      .replace(/'/g, '%27')
      .replace(/\(/g, '%28')
      .replace(/\)/g, '%29');
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
      const members: GroupMember[] = [];
      let url: string | undefined = `/groups/${groupId}/members`;

      while (url) {
        const response = await client.api(url).get();
        if (response.value) {
          for (const m of response.value) {
            members.push(GroupMemberSchema.parse(m));
          }
        }
        url = response['@odata.nextLink'];
      }

      return members;
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

  private escapeXhtml(value: string): string {
    return value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  @Span()
  public async createPage(
    client: Client,
    sectionId: string,
    title: string,
    contentHtml: string,
  ): Promise<Page> {
    const escapedTitle = this.escapeXhtml(title);
    const html = `<!DOCTYPE html>
<html>
  <head><title>${escapedTitle}</title></head>
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
