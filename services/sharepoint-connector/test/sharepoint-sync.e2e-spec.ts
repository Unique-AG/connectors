import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import type { RequestDocument } from 'graphql-request';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../src/app.module';
import { GraphClientFactory } from '../src/microsoft-apis/graph/graph-client.factory';
import { SharepointRestClientService } from '../src/microsoft-apis/sharepoint-rest/sharepoint-rest-client.service';
import { SchedulerService } from '../src/scheduler/scheduler.service';
import { HttpClientService } from '../src/shared/services/http-client.service';
import { SharepointSynchronizationService } from '../src/sharepoint-synchronization/sharepoint-synchronization.service';
import { IngestionHttpClient } from '../src/unique-api/clients/ingestion-http.client';
import {
  INGESTION_CLIENT,
  SCOPE_MANAGEMENT_CLIENT,
} from '../src/unique-api/clients/unique-graphql.client';
import type { ContentUpsertMutationInput } from '../src/unique-api/unique-file-ingestion/unique-file-ingestion.consts';
import type { AddAccessesMutationInput } from '../src/unique-api/unique-files/unique-files.consts';
import { MockGraphClient } from './test-utils/mock-graph-client';
import { MockHttpClientService } from './test-utils/mock-http-client.service';
import { MockIngestionHttpClient } from './test-utils/mock-ingestion-http.client';
import { MockSharepointRestClientService } from './test-utils/mock-sharepoint-rest-client.service';
import {
  createUniqueStatefulMock,
  type UniqueStatefulMock,
} from './test-utils/unique-stateful-mock';

// Helper to extract operation name from GraphQL document
function extractOperationName(document: RequestDocument): string {
  const docString =
    typeof document === 'string'
      ? document
      : ((document as { loc?: { source?: { body?: string } } }).loc?.source?.body ??
        document.toString());
  const match = docString.match(/(?:mutation|query)\s+(\w+)/);
  return match?.[1] || 'Unknown';
}

// Helper to get GraphQL operations by name from mock calls
type GraphqlCall<TVariables extends object> = [RequestDocument, TVariables?];
function getGraphQLOperations<TVariables extends object = Record<string, unknown>>(
  mockClient: { request: { mock: { calls: unknown[][] } } },
  operationName?: string,
) {
  const calls = mockClient.request.mock.calls as unknown as Array<GraphqlCall<TVariables>>;

  return calls
    .map(([document, variables]) => ({
      operationName: extractOperationName(document),
      variables: (variables ?? ({} as TVariables)) as TVariables,
    }))
    .filter((call) => !operationName || call.operationName === operationName);
}

describe('SharePoint synchronization (e2e)', () => {
  let app: INestApplication;
  let mockGraphClient: MockGraphClient;
  let mockSharepointRestClientService: MockSharepointRestClientService;
  let mockHttpClientService: MockHttpClientService;
  let mockIngestionHttpClient: MockIngestionHttpClient;
  let uniqueMock: UniqueStatefulMock;
  let mockIngestionGraphqlClient: UniqueStatefulMock['ingestionClient'];
  let mockScopeGraphqlClient: UniqueStatefulMock['scopeManagementClient'];

  beforeEach(async () => {
    mockGraphClient = new MockGraphClient();
    mockSharepointRestClientService = new MockSharepointRestClientService();
    mockHttpClientService = new MockHttpClientService();
    mockIngestionHttpClient = new MockIngestionHttpClient();
    uniqueMock = createUniqueStatefulMock();
    mockIngestionGraphqlClient = uniqueMock.ingestionClient;
    mockScopeGraphqlClient = uniqueMock.scopeManagementClient;

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    })
      .overrideProvider(GraphClientFactory)
      .useValue({
        createClient: () => mockGraphClient,
      })
      .overrideProvider(SharepointRestClientService)
      .useValue(mockSharepointRestClientService)
      .overrideProvider(HttpClientService)
      .useValue(mockHttpClientService)
      .overrideProvider(IngestionHttpClient)
      .useValue(mockIngestionHttpClient)
      .overrideProvider(INGESTION_CLIENT)
      .useValue(mockIngestionGraphqlClient)
      .overrideProvider(SCOPE_MANAGEMENT_CLIENT)
      .useValue(mockScopeGraphqlClient)
      .overrideProvider(SchedulerService)
      .useValue({
        onModuleInit: () => {},
        onModuleDestroy: () => {},
      })
      .compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterEach(async () => {
    if (app) {
      await app.close();
    }

    // Clear mock call history
    mockIngestionHttpClient.request.mockClear();
    mockHttpClientService.request.mockClear();
    mockIngestionGraphqlClient.request.mockClear();
    mockScopeGraphqlClient.request.mockClear();
  });

  describe('Content Ingestion', () => {
    describe('when syncing a pdf file', () => {
      it('stores content with correct mimeType and title in the ingestion store', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify the content was stored with correct values
        const storedContents = [...uniqueMock.store.contentsByKey.values()];
        expect(storedContents).toHaveLength(1);

        const pdfContent = storedContents.find((c) => c.mimeType === 'application/pdf');
        expect(pdfContent).toEqual(
          expect.objectContaining({
            title: 'test.pdf',
            mimeType: 'application/pdf',
            ownerType: 'Scope',
          }),
        );
        expect(pdfContent?.key).toContain('item-1');
      });
    });

    describe('when syncing an xlsx file', () => {
      const xlsxMimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';

      beforeEach(() => {
        const item = mockGraphClient.driveItems[0];
        if (item?.file) {
          item.file.mimeType = xlsxMimeType;
          item.name = 'report.xlsx';
          if (item.listItem?.fields) {
            item.listItem.fields.FileLeafRef = 'report.xlsx';
          }
        }
      });

      it('sends file-diff request with correct sourceKind, sourceName, and file metadata', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify the file-diff request was made with correct payload
        const fileDiffCalls = mockIngestionHttpClient.request.mock.calls;
        expect(fileDiffCalls).toHaveLength(1);

        const callArgs = fileDiffCalls[0]?.[0];
        const requestBody = JSON.parse(callArgs.body);

        expect(requestBody.sourceKind).toBe('MICROSOFT_365_SHAREPOINT');
        expect(requestBody.sourceName).toBe('Sharepoint');
        expect(requestBody.partialKey).toBe('11111111-1111-4111-8111-111111111111');
        expect(requestBody.fileList).toHaveLength(1);
        expect(requestBody.fileList[0].key).toContain('item-1');
        expect(requestBody.fileList[0].updatedAt).toBe('2025-01-02T00:00:00Z');
      });

      it('stores xlsx content with correct mimeType and title', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify the content was stored with correct xlsx values
        const storedContents = [...uniqueMock.store.contentsByKey.values()];
        expect(storedContents).toHaveLength(1);

        const xlsxContent = storedContents[0];
        expect(xlsxContent?.mimeType).toBe(xlsxMimeType);
        expect(xlsxContent?.title).toBe('report.xlsx');
        expect(xlsxContent?.ownerType).toBe('Scope');
        expect(xlsxContent?.key).toContain('item-1');
      });
    });

    describe('when file is not marked for sync', () => {
      beforeEach(() => {
        const item = mockGraphClient.driveItems[0];
        if (item?.listItem?.fields) {
          item.listItem.fields.SyncFlag = false;
        }
      });

      it('does not store any content in the ingestion store', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify no content was stored
        const storedContents = [...uniqueMock.store.contentsByKey.values()];
        expect(storedContents).toHaveLength(0);
      });

      it('sends empty fileList in file-diff request', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        const fileDiffCalls = mockIngestionHttpClient.request.mock.calls;
        expect(fileDiffCalls).toHaveLength(1);

        const callArgs = fileDiffCalls[0]?.[0];
        const requestBody = JSON.parse(callArgs.body);
        expect(requestBody.fileList).toHaveLength(0);
      });
    });

    describe('when file exceeds size limit', () => {
      beforeEach(() => {
        const item = mockGraphClient.driveItems[0];
        if (item) {
          item.size = 999999999;
        }
      });

      it('does not store any content in the ingestion store', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify no content was stored due to size limit
        const storedContents = [...uniqueMock.store.contentsByKey.values()];
        expect(storedContents).toHaveLength(0);
      });

      it('sends empty fileList in file-diff request', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        const fileDiffCalls = mockIngestionHttpClient.request.mock.calls;
        expect(fileDiffCalls).toHaveLength(1);

        const callArgs = fileDiffCalls[0]?.[0];
        const requestBody = JSON.parse(callArgs.body);
        expect(requestBody.fileList).toHaveLength(0);
      });
    });

    describe('when multiple files have mixed sync flags', () => {
      beforeEach(() => {
        // Add a second item not marked for sync
        const syncedItem = mockGraphClient.driveItems[0];
        if (!syncedItem) return;

        const unsyncedItem = JSON.parse(JSON.stringify(syncedItem));
        unsyncedItem.id = 'item-2';
        unsyncedItem.name = 'hidden.pdf';
        if (unsyncedItem.listItem?.fields) {
          unsyncedItem.listItem.fields.SyncFlag = false;
          unsyncedItem.listItem.fields.FileLeafRef = 'hidden.pdf';
        }

        mockGraphClient.driveItems = [syncedItem, unsyncedItem];
      });

      it('only includes marked file in file-diff request', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify only marked file is in fileList
        const fileDiffCalls = mockIngestionHttpClient.request.mock.calls;
        expect(fileDiffCalls).toHaveLength(1);

        const callArgs = fileDiffCalls[0]?.[0];
        const requestBody = JSON.parse(callArgs.body);

        expect(requestBody.fileList).toHaveLength(1);
        expect(requestBody.fileList[0].key).toContain('item-1');
        expect(requestBody.fileList[0].key).not.toContain('item-2');
      });

      it('only stores the marked file content', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify only the marked file was stored
        const storedContents = [...uniqueMock.store.contentsByKey.values()];
        expect(storedContents).toHaveLength(1);

        const content = storedContents[0];
        expect(content?.title).toBe('test.pdf');
        expect(content?.key).toContain('item-1');
        expect(content?.key).not.toContain('item-2');
      });
    });
  });

  describe('Permissions Sync', () => {
    describe('when file has user with read permission', () => {
      it('stores content with user file access in the store', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify content was stored with file access permissions
        const storedContents = [...uniqueMock.store.contentsByKey.values()];
        expect(storedContents).toHaveLength(1);

        const content = storedContents[0];
        expect(content?.fileAccess).toBeDefined();
        expect(content?.fileAccess.length).toBeGreaterThanOrEqual(1);

        // Verify at least one user access was granted
        const hasUserAccess = content?.fileAccess.some((access) => access.startsWith('u:'));
        expect(hasUserAccess).toBe(true);
      });

      it('maps SharePoint user permission to Unique user access', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify the GraphQL operations for file access were made with correct entity types
        const accessCalls = getGraphQLOperations<AddAccessesMutationInput>(
          mockIngestionGraphqlClient,
          'CreateFileAccessesForContents',
        );

        // Verify calls were made and contain user entity type
        expect(accessCalls.length).toBeGreaterThanOrEqual(1);
        const firstCall = accessCalls[0];
        expect(firstCall?.variables.fileAccesses).toBeDefined();
        expect(firstCall?.variables.fileAccesses.length).toBeGreaterThanOrEqual(1);

        const hasUserEntity = firstCall?.variables.fileAccesses.some(
          (fa) => fa.entityType === 'USER',
        );
        expect(hasUserEntity).toBe(true);
      });
    });

    describe('when file has no external permissions', () => {
      beforeEach(() => {
        mockGraphClient.permissions['item-1'] = [];
      });

      it('stores content without file access permissions', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // Verify content was stored
        const storedContents = [...uniqueMock.store.contentsByKey.values()];
        expect(storedContents).toHaveLength(1);

        // Content should exist but without additional file access grants
        const content = storedContents[0];
        expect(content?.title).toBe('test.pdf');
      });

      it('sends file-diff request with the file included', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        const fileDiffCalls = mockIngestionHttpClient.request.mock.calls;
        expect(fileDiffCalls).toHaveLength(1);

        const callArgs = fileDiffCalls[0]?.[0];
        const requestBody = JSON.parse(callArgs.body);
        expect(requestBody.fileList).toHaveLength(1);
        expect(requestBody.fileList[0].key).toContain('item-1');
      });
    });
  });

  describe('Integration', () => {
    it('returns success status after synchronization', async () => {
      const service = app.get(SharepointSynchronizationService);
      const result = await service.synchronize();

      expect(result).toEqual({ status: 'success' });
    });

    it('stores content with complete metadata in the ingestion store', async () => {
      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      // Verify content was stored with all required fields
      const storedContents = [...uniqueMock.store.contentsByKey.values()];
      expect(storedContents).toHaveLength(1);

      const content = storedContents[0];
      expect(content).toEqual(
        expect.objectContaining({
          title: 'test.pdf',
          mimeType: 'application/pdf',
          ownerType: 'Scope',
          ownerId: expect.any(String),
        }),
      );
      expect(content?.key).toContain('item-1');
      expect(content?.id).toBeDefined();
    });

    it('sends file-diff request with correct source configuration', async () => {
      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      const fileDiffCalls = mockIngestionHttpClient.request.mock.calls;
      expect(fileDiffCalls).toHaveLength(1);

      const callArgs = fileDiffCalls[0]?.[0];
      const requestBody = JSON.parse(callArgs.body);

      expect(requestBody.sourceKind).toBe('MICROSOFT_365_SHAREPOINT');
      expect(requestBody.sourceName).toBe('Sharepoint');
      expect(requestBody.partialKey).toBe('11111111-1111-4111-8111-111111111111');
    });

    it('makes HTTP request for file download', async () => {
      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      // Verify file download HTTP request was made
      const httpCalls = mockHttpClientService.request.mock.calls;
      expect(httpCalls.length).toBeGreaterThanOrEqual(1);
    });

    it('performs all GraphQL operations for content upsert and file access', async () => {
      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      // Verify ContentUpsert was called
      const upsertCalls = getGraphQLOperations<ContentUpsertMutationInput>(
        mockIngestionGraphqlClient,
        'ContentUpsert',
      );
      expect(upsertCalls).toHaveLength(1);
      expect(upsertCalls[0]?.variables.input.title).toBe('test.pdf');
      expect(upsertCalls[0]?.variables.input.mimeType).toBe('application/pdf');

      // Verify CreateFileAccessesForContents was called
      const accessCalls = getGraphQLOperations<AddAccessesMutationInput>(
        mockIngestionGraphqlClient,
        'CreateFileAccessesForContents',
      );
      expect(accessCalls.length).toBeGreaterThanOrEqual(1);
    }, 20000);
  });
});