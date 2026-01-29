# E2E Test Infrastructure - Usage Guide

## Overview

The e2e tests now use **stateful mocks with request capture** to verify that the SharePoint connector sends correct payloads to Unique services.

## Key Components

### 1. RequestCapture

Captures all HTTP requests made during tests:

```typescript
const capture = new RequestCapture();

// After running sync
const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
const graphqlCalls = capture.getGraphQLOperations('ContentUpsert');
```

### 2. Stateful Mocks

All mock services have mutable public properties:

- `MockGraphApiService` - SharePoint data
  - `items: SharepointContentItem[]`
  - `directories: SharepointDirectoryItem[]`
  - `permissions: Record<string, SimplePermission[]>`
  - `maxFileSizeToIngestBytes: number`
  - `allowedMimeTypes: string[]`

- `MockIngestionHttpClient` - Unique ingestion responses
  - `fileDiffResponse: { newFiles, updatedFiles, movedFiles, deletedFiles }`

- `MockHttpClientService` - HTTP upload responses
  - `response: { statusCode, body }`

- `MockSharepointRestClientService` - SharePoint REST
  - `groupMemberships: Record<string, any[]>`

## Writing Tests

### Pattern: Direct Property Mutation

```typescript
describe('when syncing an xlsx file', () => {
  beforeEach(() => {
    // Mutate only what's relevant for this scenario
    mockGraphApiService.items[0].item.file.mimeType = 
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
    mockGraphApiService.items[0].item.name = 'report.xlsx';
    mockGraphApiService.items[0].fileName = 'report.xlsx';
  });

  it('sends correct mimeType to file-diff', async () => {
    await service.synchronize();
    
    const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
    expect(fileDiffCalls[0].body).toMatchObject({
      sourceKind: 'MICROSOFT_365_SHAREPOINT',
      fileList: expect.arrayContaining([
        expect.objectContaining({
          key: expect.stringContaining('item-1'),
        }),
      ]),
    });
  });
});
```

### Pattern: Inherited State

Nested describe blocks layer mutations:

```typescript
describe('Permissions', () => {
  // Base: has default permission
  
  describe('when file has no permissions', () => {
    beforeEach(() => {
      mockGraphApiService.permissions['item-1'] = [];
    });
    
    it('processes without external permissions', async () => {
      // ...
    });
  });
});
```

## Mock Behavior

`MockGraphApiService.getAllSiteItems` automatically filters items by:
1. **SyncFlag** - Must be true
2. **File size** - Must be ≤ `maxFileSizeToIngestBytes`
3. **MIME type** - Must be in `allowedMimeTypes` or be an .aspx file

This matches the real `GraphApiService` + `FileFilterService` behavior.

## Example Scenarios

### Test: File Not Marked for Sync

```typescript
beforeEach(() => {
  mockGraphApiService.items[0].item.listItem.fields.SyncFlag = false;
});

it('excludes file from synchronization', async () => {
  await service.synchronize();
  
  const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
  if (fileDiffCalls.length > 0) {
    expect(fileDiffCalls[0].body.fileList).toHaveLength(0);
  }
});
```

### Test: File Exceeds Size Limit

```typescript
beforeEach(() => {
  mockGraphApiService.items[0].item.size = 999999999;
});

it('excludes file from file-diff request', async () => {
  await service.synchronize();
  
  const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
  if (fileDiffCalls.length > 0) {
    expect(fileDiffCalls[0].body.fileList).toHaveLength(0);
  }
});
```

### Test: Multiple Files with Mixed States

```typescript
beforeEach(() => {
  mockGraphApiService.items = [
    mockGraphApiService.createDefaultItem(), // SyncFlag=true, will sync
    {
      ...mockGraphApiService.createDefaultItem(),
      item: {
        ...mockGraphApiService.createDefaultItem().item,
        id: 'item-2',
        listItem: {
          ...mockGraphApiService.createDefaultItem().item.listItem,
          fields: { ...mockGraphApiService.createDefaultItem().item.listItem.fields, SyncFlag: false }
        }
      }
    }
  ];
});

it('only syncs marked files', async () => {
  await service.synchronize();
  
  const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
  expect(fileDiffCalls[0].body.fileList).toHaveLength(1);
  expect(fileDiffCalls[0].body.fileList[0].key).toContain('item-1');
});
```

## Adding New Test Cases

1. Add a new `describe` block
2. Use `beforeEach` to mutate mock state
3. Run synchronization
4. Assert on captured requests using `capture.getRestCalls()` or `capture.getGraphQLOperations()`

## Benefits

- ✅ **DRY** - Tests only specify what's different from defaults
- ✅ **No fixtures duplication** - One mock, many scenarios
- ✅ **Request verification** - Verify actual payloads, not just method calls
- ✅ **Easy maintenance** - Change defaults in one place
- ✅ **Inherited state** - Nested describes build on parent state
