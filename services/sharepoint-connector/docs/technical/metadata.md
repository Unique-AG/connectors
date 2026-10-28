<!-- confluence-page-id: 2133983459 -->
<!-- confluence-space-key: PUBDOC -->

## Ingested Metadata

The connector retrieves documents and their metadata via the Microsoft Graph API. For each document, it calls the Graph drive items endpoint with an expanded `listItem` and `fields`, which returns all SharePoint list columns. During ingestion, the connector passes these column values as metadata to the Unique platform.

### Regular Documents (Document Libraries)

For regular documents in document libraries, the connector passes through **all SharePoint column values** as-is (the full `fields` bag from Graph), plus the following derived fields:

| Field | Source | Description |
| ----- | ------ | ----------- |
| `Url` | `webUrl` property on the list item | The document's web URL |
| `Link` | Same as `Url` | Alias for the document's web URL |
| `Path` | Parent reference path | The folder path within the drive |
| `DriveId` | Drive identifier | The Microsoft Graph drive ID |
| `ItemInternalId` | `id` property from Graph API response | The Microsoft Graph drive item ID (a longer unique identifier) |
| `Filename` | `FileLeafRef` SharePoint field | The file's leaf name |
| `Author` | `createdBy` property | Structured object with `email`, `displayName`, and `id` |

Native SharePoint columns that come through include (among others): `FileLeafRef`, `Modified`, `Created`, `ContentType`, `AuthorLookupId`, `EditorLookupId`, `FileSizeDisplay`, `Title`, plus any custom columns defined on the library.

#### Graph API Call

```
GET /drives/{driveId}/items/{itemId}/children
    ?$select=id,name,webUrl,size,createdDateTime,lastModifiedDateTime,createdBy,folder,file,listItem,parentReference
    &$expand=listItem($expand=fields)
```

### SitePages

SitePages (pages created directly in SharePoint such as news posts or wiki pages) are handled differently from regular documents:

| Field | Source | Description |
| ----- | ------ | ----------- |
| `Url` | `webUrl` property on the list item | The page's web URL |
| `Link` | Same as `Url` | Alias for the page's web URL |
| `Path` | `webUrl` property | The page's web URL (used as folder path) |
| `DriveId` | SitePages list ID | The SitePages list identifier (not a document library drive ID) |
| `ItemInternalId` | `id` property from Graph API response | Sequential list item ID (e.g. 1, 2, 3), unique only within that SitePages list |
| `Filename` | `FileLeafRef` SharePoint field | The page's file name |
| `Author` | `createdBy` property | Structured object with `email`, `displayName`, and `id` |
| `ModerationStatus` | `_ModerationStatus` SharePoint field | Content approval status |

SitePages carry a **reduced set** of SharePoint column values: `FileLeafRef`, `FileSizeDisplay`, `Title`, `AuthorLookupId`, `EditorLookupId`, `_ModerationStatus`, and the sync flag column.

#### Graph API Call

```
GET /sites/{siteId}/lists/{listId}/items
    ?$select=id,createdDateTime,lastModifiedDateTime,webUrl,createdBy,lastModifiedBy
    &$expand=fields($select=FileLeafRef,FileSizeDisplay,_ModerationStatus,Title,AuthorLookupId,EditorLookupId)
```

### List Item Attachments

Each attachment of an in-scope list item is ingested as its own document. It carries **all SharePoint column values of its list item** (the full `fields` bag from Graph), so every attachment of an item has the same column values, plus the following derived fields:

| Field | Source | Description |
| ----- | ------ | ----------- |
| `Url` | Attachment's server-relative URL on the SharePoint origin | The attachment's absolute URL |
| `Link` | Same as `Url` | Alias for the attachment's URL |
| `Path` | Item folder name | `/{item folder}`, the item's folder within its list folder in Unique |
| `DriveId` | List ID | The list identifier (not a document library drive ID) |
| `ItemInternalId` | `id` property from Graph API response | Sequential list item ID, unique only within that list |
| `Filename` | Attachment file name | The attachment's file name |
| `Author` | `createdBy` property of the list item | Structured object with `email`, `displayName`, and `id` |
| `ModerationStatus` | `_ModerationStatus` SharePoint field | Content approval status (only present on lists with content approval) |

Graph returns `_ModerationStatus` only on lists with content approval enabled, so the column and the derived `ModerationStatus` are absent on other lists.

#### Graph API Call

```
GET /sites/{siteId}/lists/{listId}/items
    ?$select=id,createdDateTime,lastModifiedDateTime,webUrl,createdBy,lastModifiedBy
    &$expand=fields
```

### Key Differences Between Regular Documents, SitePages and List Item Attachments

| Aspect | Regular Documents | SitePages | List Item Attachments |
| ------ | ----------------- | --------- | --------------------- |
| **Metadata fields** | Full set of all SharePoint column values | Reduced set (`FileLeafRef`, `FileSizeDisplay`, `Title`, `AuthorLookupId`, `EditorLookupId`, `_ModerationStatus`, sync column) | Full set of the list item's column values |
| **Path** | Folder path within the drive | Page's web URL | `/{item folder}` |
| **ItemInternalId** | Graph API drive item ID (long unique identifier) | Sequential list item ID (e.g. 1, 2, 3), unique only within that SitePages list | Sequential list item ID, unique only within that list |
| **DriveId** | Document library drive ID | SitePages list ID | List ID |
| **ModerationStatus** | Not present | Content approval status from `_ModerationStatus` field | Content approval status, only on lists with content approval |

## Related Documentation

- [Flows](./flows.md) - Content sync, ASPX page processing, file diff mechanism
- [Architecture](./architecture.md) - System components and Graph API endpoints
- [Permissions](./permissions.md) - Required API permissions

## Standard References

- [Microsoft Graph API - DriveItem](https://learn.microsoft.com/en-us/graph/api/resources/driveitem) - DriveItem resource
- [Microsoft Graph API - ListItem](https://learn.microsoft.com/en-us/graph/api/resources/listitem) - ListItem resource
- [Microsoft Graph API - FieldValueSet](https://learn.microsoft.com/en-us/graph/api/resources/fieldvalueset) - SharePoint column values
