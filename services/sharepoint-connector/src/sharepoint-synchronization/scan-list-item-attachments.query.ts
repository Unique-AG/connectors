import assert from 'node:assert';
import type { List } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { concat, countBy, filter, flatMap, isNonNullish, map, pipe } from 'remeda';
import { Config } from '../config';
import { FileFilterService } from '../microsoft-apis/graph/file-filter.service';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type { ListItem } from '../microsoft-apis/graph/types/sharepoint.types';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { SharepointRestClientService } from '../microsoft-apis/sharepoint-rest/sharepoint-rest-client.service';
import { isListViewThresholdError } from '../microsoft-apis/sharepoint-rest/sharepoint-rest-http.service';
import { columnsOf, resolveColumnName } from '../utils/list-columns.util';
import type { ManagedPath } from '../utils/paths.util';
import { buildAttachmentAbsoluteUrl } from '../utils/sharepoint.util';
import { createSmeared, type Smeared } from '../utils/smeared';

export interface ListItemAttachmentsScanOptions {
  itemNameColumnName: string;
  // In Unique, this web's list folders sit next to its library folders and the folders of its
  // synced subsites. Libraries come from the same lists response, but subsites are discovered
  // separately, so their folder names are passed in to keep a list from merging into a subsite.
  subsiteFolderNames: string[];
}

export class UnsupportedListReadSecurityError extends Error {
  public constructor(listName: Smeared, listId: string) {
    super(
      `List "${listName}" (${listId}) is unsupported: users can read only their own items ` +
        `(ReadSecurity 2). Aborting the site sync.`,
    );
    this.name = 'UnsupportedListReadSecurityError';
  }
}

export class ListViewThresholdExceededError extends Error {
  public constructor(listName: Smeared, listId: string) {
    super(
      `List "${listName}" (${listId}) is unsupported: it has more than 5000 items, the ` +
        `SharePoint list view threshold. Aborting the site sync.`,
    );
    this.name = 'ListViewThresholdExceededError';
  }
}

interface GenericList {
  list: List;
  listId: string;
  displayName: Smeared;
}

interface SyncedList extends GenericList {
  syncColumn: string;
  itemNameColumn: string;
  folderName: Smeared;
}

interface SiteWeb {
  siteName: Smeared;
  managedPath: ManagedPath;
}

interface ScannedAttachment {
  fileName: Smeared;
  absoluteUrl: Smeared;
  size: number;
}

@Injectable()
export class ScanListItemAttachmentsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
    private readonly sharepointRestClientService: SharepointRestClientService,
    private readonly fileFilterService: FileFilterService,
  ) {}

  public async execute(
    siteId: Smeared,
    syncColumnName: string,
    options: ListItemAttachmentsScanOptions,
    lists: List[],
  ): Promise<SharepointContentItem[]> {
    const logPrefix = `[Site: ${siteId}]`;
    const syncedLists = this.resolveSyncedLists(lists, syncColumnName, options, logPrefix);
    if (syncedLists.length === 0) {
      return [];
    }

    if (this.configService.get('sharepoint.auth', { infer: true }).mode !== 'certificate') {
      this.logger.warn(
        `${logPrefix} Skipping list attachment scan because SharePoint REST rejects app-only ` +
          `tokens obtained with a client secret. Attachments ingested from this site earlier ` +
          `will be deleted. Drives and SitePages are unaffected.`,
      );
      return [];
    }

    const siteWeb = await this.graphApiService.getSiteInfo(siteId);
    const attachmentsPerList: SharepointContentItem[][] = [];
    for (const syncedList of syncedLists) {
      attachmentsPerList.push(await this.scanList(siteId, siteWeb, syncedList, logPrefix));
    }
    const attachments = attachmentsPerList.flat();

    this.logger.log(`${logPrefix} Found ${attachments.length} list item attachments`);
    return attachments;
  }

  private resolveSyncedLists(
    lists: List[],
    syncColumnName: string,
    { itemNameColumnName, subsiteFolderNames }: ListItemAttachmentsScanOptions,
    logPrefix: string,
  ): SyncedList[] {
    const genericLists = pipe(lists, filter(isGenericListCandidate), map(toGenericList));
    // Named over every generic list, synced or not, so enabling sync on one list never renames
    // the folder of another.
    const folderNames = assignListFolderNames(
      genericLists,
      takenFolderNames(lists, subsiteFolderNames),
    );

    return pipe(
      genericLists,
      map((genericList) =>
        this.resolveListColumns(genericList, syncColumnName, itemNameColumnName, logPrefix),
      ),
      filter(isNonNullish),
      map((list) => ({
        ...list,
        folderName: createSmeared(folderNames.get(list.listId) ?? list.listId),
      })),
    );
  }

  private resolveListColumns(
    genericList: GenericList,
    syncColumnName: string,
    itemNameColumnName: string,
    logPrefix: string,
  ): Omit<SyncedList, 'folderName'> | undefined {
    const columns = columnsOf(genericList.list);
    const syncColumn = resolveColumnName(columns, syncColumnName);
    if (!syncColumn) {
      return undefined;
    }

    const itemNameColumn = resolveColumnName(columns, itemNameColumnName);
    if (!itemNameColumn) {
      this.logger.warn(
        `${logPrefix} Skipping list ${genericList.listId} "${genericList.displayName}": ` +
          `item name column "${itemNameColumnName}" was not found. Treated as empty list.`,
      );
      return undefined;
    }

    return { ...genericList, syncColumn, itemNameColumn };
  }

  private async scanList(
    siteId: Smeared,
    siteWeb: SiteWeb,
    syncedList: SyncedList,
    logPrefix: string,
  ): Promise<SharepointContentItem[]> {
    const { listId, displayName } = syncedList;
    this.logger.log(`${logPrefix} Found list ${listId} "${displayName}" for attachment sync`);

    // Checked before reading items: with ReadSecurity 2 the app sees only items it created, so
    // the list reads as empty and its ingested attachments would be deleted.
    await this.assertReadSecuritySupported(siteWeb, syncedList);

    const items = await this.fetchInScopeItems(siteId, syncedList);
    if (items.length === 0) {
      return [];
    }

    const attachmentsByItemId = await this.fetchAttachmentsByItemId(siteWeb, syncedList);
    const itemFolderNames = assignItemFolderNames(
      items.map((item) => ({
        itemId: item.id,
        rawName: readColumnText(item.fields, syncedList.itemNameColumn),
      })),
    );

    return pipe(
      items,
      flatMap((item) =>
        map(attachmentsByItemId.get(item.id) ?? [], (attachment) => ({
          item,
          itemFolderName: itemFolderNames.get(item.id) ?? item.id,
          attachment,
        })),
      ),
      filter(({ attachment }) => this.isAttachmentAllowed(attachment, listId, logPrefix)),
      map(
        ({ item, itemFolderName, attachment }): SharepointContentItem => ({
          itemType: 'listItemAttachment',
          item,
          siteId,
          driveId: listId,
          driveName: syncedList.folderName.value,
          folderPath: `/${itemFolderName}`,
          fileName: attachment.fileName.value,
          attachment: { absoluteUrl: attachment.absoluteUrl.value, size: attachment.size },
        }),
      ),
    );
  }

  private async fetchInScopeItems(siteId: Smeared, syncedList: SyncedList): Promise<ListItem[]> {
    const items = await this.graphApiService.getListItems(siteId, syncedList.listId, {
      select: 'id,createdDateTime,lastModifiedDateTime,webUrl,createdBy,lastModifiedBy',
      expand: 'fields',
    });
    return items.filter((item) =>
      this.fileFilterService.isGenericListItemInScope(item.fields, syncedList.syncColumn),
    );
  }

  private async assertReadSecuritySupported(
    { siteName, managedPath }: SiteWeb,
    { listId, displayName }: SyncedList,
  ): Promise<void> {
    const readSecurity = await this.sharepointRestClientService.getListReadSecurity(
      siteName,
      managedPath,
      listId,
    );
    if (readSecurity === 2) {
      throw new UnsupportedListReadSecurityError(displayName, listId);
    }
  }

  private async fetchAttachmentsByItemId(
    { siteName, managedPath }: SiteWeb,
    { listId, displayName }: SyncedList,
  ): Promise<Map<string, ScannedAttachment[]>> {
    const folders = await this.sharepointRestClientService
      .getListItemAttachments(siteName, managedPath, listId)
      .catch((error: unknown) => {
        throw isListViewThresholdError(error)
          ? new ListViewThresholdExceededError(displayName, listId)
          : error;
      });
    const baseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });

    return new Map(
      folders.map((folder) => [
        folder.Name,
        folder.Files.map((file) => ({
          fileName: createSmeared(file.Name),
          absoluteUrl: createSmeared(buildAttachmentAbsoluteUrl(baseUrl, file.ServerRelativeUrl)),
          size: Number(file.Length),
        })),
      ]),
    );
  }

  private isAttachmentAllowed(file: ScannedAttachment, listId: string, logPrefix: string): boolean {
    if (this.fileFilterService.isAttachmentValidForIngestion(file)) {
      return true;
    }
    this.logger.debug(
      `${logPrefix} Skipping attachment "${file.fileName}" (${file.size} bytes) of list ` +
        `${listId}: its MIME type is not allowed, or it is empty or over the size limit`,
    );
    return false;
  }
}

function isGenericListCandidate(list: List): boolean {
  if (!list.id || list.name?.toLowerCase() === 'sitepages') {
    return false;
  }
  if (list.system != null) {
    return false;
  }
  const info = list.list;
  if (!info || info.hidden) {
    return false;
  }
  return !isLibraryListTemplate(info.template);
}

function isLibraryListTemplate(template: string | null | undefined): boolean {
  if (!template) {
    return false;
  }
  const normalized = template.toLowerCase();
  return normalized.includes('library') || normalized === 'xmlform';
}

function toGenericList(list: List): GenericList {
  assert.ok(list.id, 'Generic list is missing an id');
  return {
    list,
    listId: list.id,
    displayName: createSmeared(list.displayName || list.name || list.id),
  };
}

// A list folder shares its parent with library folders, named by URL rather than title, and with
// subsite folders.
function takenFolderNames(lists: List[], subsiteFolderNames: string[]): Set<string> {
  return new Set(
    pipe(
      lists,
      filter((list) => isLibraryListTemplate(list.list?.template)),
      map((list) => list.name),
      filter(isNonNullish),
      concat(subsiteFolderNames),
    ),
  );
}

// Scope names are path segments. `/` would create an extra folder, and Unique rejects the other
// characters below when creating a scope from a path. Control characters are rejected the same way.
const SCOPE_NAME_INVALID_CHARACTERS = new Set('\\/:*?"<>|#%'.split(''));

function sanitizeScopeName(value: string): string {
  return Array.from(value, (character) => {
    const code = character.charCodeAt(0);
    if (code <= 31 || SCOPE_NAME_INVALID_CHARACTERS.has(character)) {
      return '_';
    }
    return character;
  })
    .join('')
    .trim();
}

// The item-name column can be of any type. Values other than text, numbers and Yes/No, such as
// multi-choice or person values, give an empty name, so the item ID is used instead.
function readColumnText(fields: Record<string, unknown>, columnName: string): string {
  const value = fields[columnName];
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '';
}

// List titles are unique within a web, but sanitizing can merge two of them.
function assignListFolderNames(
  lists: ReadonlyArray<GenericList>,
  takenFolderNames: ReadonlySet<string>,
): Map<string, string> {
  return assignDistinctNames(
    lists.map(({ listId, displayName }) => {
      const name = sanitizeScopeName(displayName.value) || listId;
      return { key: listId, candidates: [name, `${name} (List)`, `${name} (${listId})`] };
    }),
    takenFolderNames,
  );
}

function assignItemFolderNames(
  items: ReadonlyArray<{ itemId: string; rawName: string }>,
): Map<string, string> {
  return assignDistinctNames(
    items.map(({ itemId, rawName }) => {
      const name = sanitizeScopeName(rawName) || itemId;
      return { key: itemId, candidates: [name, `${name} (${itemId})`] };
    }),
    new Set(),
  );
}

interface NamingEntry {
  key: string;
  candidates: readonly [string, ...string[]];
}

// Names are assigned from the full set so a later run with the same entries produces the same
// folders. Every entry whose name is shared, with another entry or a taken name, moves on to its
// next candidate, so all of them change, not only the second one. Unique scope paths are
// case-sensitive, so names that differ only in case are distinct.
// The last candidate ends in the entry's unique key, which keeps it distinct from other entries
// and ends the loop. It is not checked against taken names: a clash there needs a sibling folder
// whose name already contains this entry's key.
function assignDistinctNames(
  entries: readonly NamingEntry[],
  takenNames: ReadonlySet<string>,
): Map<string, string> {
  let named = entries.map((entry) => ({ ...entry, level: 0, name: entry.candidates[0] }));
  let changed = true;

  while (changed) {
    const counts = countBy(named, (entry) => entry.name);
    const next = named.map((entry) => {
      const isShared = takenNames.has(entry.name) || (counts[entry.name] ?? 0) > 1;
      const nextName = entry.candidates[entry.level + 1];
      if (!isShared || nextName === undefined) {
        return entry;
      }
      return { ...entry, level: entry.level + 1, name: nextName };
    });
    // If we changed at least one entry, there is a next loop to check for further collisions.
    changed = next.some((entry, index) => entry.level !== named[index]?.level);
    named = next;
  }

  return new Map(named.map((entry) => [entry.key, entry.name]));
}
