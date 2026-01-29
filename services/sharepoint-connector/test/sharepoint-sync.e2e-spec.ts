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
import { baseState, type ScenarioState } from './test-state/base-state';
import { applyScenarioState } from './test-state/load-state';
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

  function cloneBaseState(): ScenarioState {
    return structuredClone(baseState);
  }

  async function runSynchronisation(state: ScenarioState): Promise<{ status: string }> {
    // Build the entire scenario state explicitly in the test body (see `test brainsstorm.md`).
    applyScenarioState({ graphClient: mockGraphClient, uniqueMock, state });

    const service = app.get(SharepointSynchronizationService);
    return await service.synchronize();
  }

  describe('Content Ingestion', () => {
    describe('when syncing a pdf file', () => {
      it('sends correct mimeType to ContentUpsert', async () => {
        await runSynchronisation(cloneBaseState());

        // Query the ingestion GraphQL client mock directly
        const upserts = getGraphQLOperations<ContentUpsertMutationInput>(
          mockIngestionGraphqlClient,
          'ContentUpsert',
        );
        expect(upserts.length).toBeGreaterThan(0);

        // Find the upsert for our test file
        const testFileUpsert = upserts.find(
          (u) => u.variables?.input?.mimeType === 'application/pdf',
        );

        expect(testFileUpsert).toBeDefined();
        expect(testFileUpsert?.variables.input).toMatchObject({
          mimeType: 'application/pdf',
          title: 'test.pdf',
        });
      });
    });

    describe('when syncing an xlsx file', () => {
      it('sends correct mimeType to file-diff', async () => {
        const state = cloneBaseState();
        const drive = state.sharepoint.libraries.find((l) => l.type === 'drive');
        if (drive?.type === 'drive' && drive.content[0]?.type === 'file') {
          drive.content[0].mock.mimeType =
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
          drive.content[0].mock.name = 'report.xlsx';
        }

        await runSynchronisation(state);

        // Verify the request was called
        expect(mockIngestionHttpClient.request).toHaveBeenCalled();

        // Parse and verify request body
        const callArgs = mockIngestionHttpClient.request.mock.calls[0]?.[0];
        expect(callArgs).toBeDefined();

        const requestBody = JSON.parse(callArgs.body);
        expect(requestBody).toMatchObject({
          sourceKind: 'MICROSOFT_365_SHAREPOINT',
          sourceName: 'Sharepoint',
          partialKey: '11111111-1111-4111-8111-111111111111',
          fileList: expect.arrayContaining([
            expect.objectContaining({
              key: expect.stringContaining('item-1'),
              updatedAt: expect.any(String),
            }),
          ]),
        });

        // Verify file is included
        expect(requestBody.fileList).toHaveLength(1);

        // Verify ContentUpsert GraphQL payload
        const upserts = getGraphQLOperations<ContentUpsertMutationInput>(
          mockIngestionGraphqlClient,
          'ContentUpsert',
        );
        expect(upserts.length).toBeGreaterThan(0);

        // Find the upsert for our xlsx file
        const xlsxUpsert = upserts.find(
          (u) =>
            u.variables?.input?.mimeType ===
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        );

        expect(xlsxUpsert).toBeDefined();
        expect(xlsxUpsert?.variables.input).toMatchObject({
          mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          title: 'report.xlsx',
        });
      });

      it('includes xlsx file in synchronization', async () => {
        const state = cloneBaseState();
        const drive = state.sharepoint.libraries.find((l) => l.type === 'drive');
        if (drive?.type === 'drive' && drive.content[0]?.type === 'file') {
          drive.content[0].mock.mimeType =
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
          drive.content[0].mock.name = 'report.xlsx';
        }

        await runSynchronisation(state);

        expect(mockIngestionHttpClient.request).toHaveBeenCalled();
      });
    });

    describe('when file is not marked for sync', () => {
      it('excludes file from synchronization', async () => {
        const state = cloneBaseState();
        const drive = state.sharepoint.libraries.find((l) => l.type === 'drive');
        if (drive?.type === 'drive' && drive.content[0]?.type === 'file') {
          drive.content[0].mock.syncFlag = false;
        }

        await runSynchronisation(state);

        // Check if request was called, and if so verify empty fileList
        if (mockIngestionHttpClient.request.mock.calls.length > 0) {
          const callArgs = mockIngestionHttpClient.request.mock.calls[0]?.[0];
          const requestBody = JSON.parse(callArgs.body);
          expect(requestBody).toMatchObject({
            fileList: [],
          });
        }
      });
    });

    describe('when file exceeds size limit', () => {
      it('excludes file from file-diff request', async () => {
        const state = cloneBaseState();
        const drive = state.sharepoint.libraries.find((l) => l.type === 'drive');
        if (drive?.type === 'drive' && drive.content[0]?.type === 'file') {
          drive.content[0].mock.size = 999999999;
        }

        await runSynchronisation(state);

        // Check if request was called, and if so verify empty fileList
        if (mockIngestionHttpClient.request.mock.calls.length > 0) {
          const callArgs = mockIngestionHttpClient.request.mock.calls[0]?.[0];
          const requestBody = JSON.parse(callArgs.body);
          expect(requestBody).toMatchObject({
            fileList: [],
          });
        }
      });
    });

    describe('when multiple files have mixed sync flags', () => {
      it('only synchronizes the marked file', async () => {
        const state = cloneBaseState();
        const drive = state.sharepoint.libraries.find((l) => l.type === 'drive');
        if (drive?.type === 'drive' && drive.content[0]?.type === 'file') {
          const hidden = structuredClone(drive.content[0]);
          hidden.mock.id = 'item-2';
          hidden.mock.name = 'hidden.pdf';
          hidden.mock.syncFlag = false;
          hidden.permissions = [];
          drive.content = [drive.content[0], hidden];
        }

        await runSynchronisation(state);

        // Verify the request was called and parse request body
        expect(mockIngestionHttpClient.request).toHaveBeenCalled();
        const callArgs = mockIngestionHttpClient.request.mock.calls[0]?.[0];
        const requestBody = JSON.parse(callArgs.body);

        expect(requestBody.fileList).toHaveLength(1);
        expect(requestBody.fileList[0]?.key).toContain('item-1');

        const upserts = getGraphQLOperations<ContentUpsertMutationInput>(
          mockIngestionGraphqlClient,
          'ContentUpsert',
        );
        expect(upserts.length).toBeGreaterThan(0);

        // Find the upsert for test.pdf
        const testPdfUpsert = upserts.find((u) => u.variables?.input?.title === 'test.pdf');

        expect(testPdfUpsert).toBeDefined();
        expect(testPdfUpsert?.variables.input).toMatchObject({
          title: 'test.pdf',
        });
      });
    });
  });

  describe('Permissions Sync', () => {
    describe('when file has user with read permission', () => {
      it('synchronizes with default permissions', async () => {
        await runSynchronisation(cloneBaseState());

        // Verify that CreateFileAccessesForContents was called on the ingestion client
        const accessCalls = getGraphQLOperations<AddAccessesMutationInput>(
          mockIngestionGraphqlClient,
          'CreateFileAccessesForContents',
        );
        expect(accessCalls.length).toBeGreaterThan(0);
      });
    });

    describe('when file has no external permissions', () => {
      it('still processes the file', async () => {
        const state = cloneBaseState();
        const drive = state.sharepoint.libraries.find((l) => l.type === 'drive');
        if (drive?.type === 'drive' && drive.content[0]?.type === 'file') {
          drive.content[0].permissions = [];
        }

        await runSynchronisation(state);

        expect(mockIngestionHttpClient.request).toHaveBeenCalled();
      });
    });
  });

  describe('Integration', () => {
    it('synchronizes content and permissions with mocked dependencies', async () => {
      const result = await runSynchronisation(cloneBaseState());

      // synchronize() returns { status: 'success' } on success
      // (we assert downstream effects instead of relying on return plumbing here)
      expect(result).toEqual({ status: 'success' });

      expect(mockIngestionHttpClient.request).toHaveBeenCalled();

      // Verify requests were tracked
      const allCalls = getGraphQLOperations(mockIngestionGraphqlClient);
      expect(allCalls.length).toBeGreaterThan(0);

      expect(mockHttpClientService.request).toHaveBeenCalled();
    }, 20000);
  });
});
