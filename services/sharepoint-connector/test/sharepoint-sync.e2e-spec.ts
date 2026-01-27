import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import { MockAgent, setGlobalDispatcher } from 'undici';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../src/app.module';
import { GraphApiService } from '../src/microsoft-apis/graph/graph-api.service';
import { SharepointRestClientService } from '../src/microsoft-apis/sharepoint-rest/sharepoint-rest-client.service';
import { SchedulerService } from '../src/scheduler/scheduler.service';
import { HttpClientService } from '../src/shared/services/http-client.service';
import { SharepointSynchronizationService } from '../src/sharepoint-synchronization/sharepoint-synchronization.service';
import { IngestionHttpClient } from '../src/unique-api/clients/ingestion-http.client';
import { FileDiffRequest } from '../src/unique-api/unique-file-ingestion/unique-file-ingestion.types';
import { MockGraphApiService } from '../src/utils/test-utils/mock-graph-api.service';
import { MockHttpClientService } from '../src/utils/test-utils/mock-http-client.service';
import { MockIngestionHttpClient } from '../src/utils/test-utils/mock-ingestion-http.client';
import { MockSharepointRestClientService } from '../src/utils/test-utils/mock-sharepoint-rest-client.service';
import { RequestCapture } from '../src/utils/test-utils/request-capture';

const fixturePath = (fileName: string) => join(process.cwd(), 'test', 'fixtures', fileName);

const loadJson = <T>(fileName: string): T =>
  JSON.parse(readFileSync(fixturePath(fileName), 'utf-8')) as T;

const ingestionGraphqlResponse = loadJson('ingestion-graphql-response.json');
const scopeGraphqlResponse = loadJson('scope-graphql-response.json');

describe('SharePoint synchronization (e2e)', () => {
  let app: INestApplication;
  let mockAgent: MockAgent;
  let mockGraphApiService: MockGraphApiService;
  let mockSharepointRestClientService: MockSharepointRestClientService;
  let mockHttpClientService: MockHttpClientService;
  let mockIngestionHttpClient: MockIngestionHttpClient;
  let capture: RequestCapture;

  beforeAll(() => {
    mockAgent = new MockAgent();
    mockAgent.disableNetConnect();
    setGlobalDispatcher(mockAgent);

    const ingestionPool = mockAgent.get('https://unique-ingestion.test');
    const scopePool = mockAgent.get('https://unique-scope.test');

    ingestionPool
      .intercept({ method: 'POST', path: '/v2/content/file-diff' })
      .reply(
        200,
        (opts) => {
          capture?.capture(
            'POST',
            '/v2/content/file-diff',
            opts.body,
            opts.headers as Record<string, string>,
          );
          return JSON.stringify(loadJson('file-diff-response.json'));
        },
        {
          headers: { 'content-type': 'application/json' },
        },
      )
      .persist();

    ingestionPool
      .intercept({ method: 'POST', path: '/graphql' })
      .reply(
        200,
        (opts) => {
          capture?.capture('POST', '/graphql', opts.body, opts.headers as Record<string, string>);
          return JSON.stringify(ingestionGraphqlResponse);
        },
        {
          headers: { 'content-type': 'application/json' },
        },
      )
      .persist();

    scopePool
      .intercept({ method: 'POST', path: '/graphql' })
      .reply(
        200,
        (opts) => {
          capture?.capture('POST', '/graphql', opts.body, opts.headers as Record<string, string>);
          return JSON.stringify(scopeGraphqlResponse);
        },
        {
          headers: { 'content-type': 'application/json' },
        },
      )
      .persist();
  });

  afterAll(async () => {
    await mockAgent.close();
  });

  beforeEach(async () => {
    capture = new RequestCapture();
    mockGraphApiService = new MockGraphApiService();
    mockSharepointRestClientService = new MockSharepointRestClientService();
    mockHttpClientService = new MockHttpClientService();
    mockIngestionHttpClient = new MockIngestionHttpClient();

    // Wrap mocks to capture requests
    // biome-ignore lint/suspicious/noExplicitAny: Test mock needs to handle any request options
    mockIngestionHttpClient.request.mockImplementation(async (options: any) => {
      capture.capture(options.method || 'POST', options.path, options.body, options.headers || {});
      return {
        statusCode: 200,
        body: {
          text: async () => JSON.stringify(mockIngestionHttpClient.fileDiffResponse),
          json: async () => mockIngestionHttpClient.fileDiffResponse,
        },
        headers: {},
      };
    });

    // biome-ignore lint/suspicious/noExplicitAny: Test mock needs to handle any request options
    mockHttpClientService.request.mockImplementation(async (options: any) => {
      capture.capture(options.method || 'PUT', options.path, options.body, options.headers || {});
      return {
        statusCode: mockHttpClientService.response.statusCode,
        body: {
          text: async () => JSON.stringify(mockHttpClientService.response.body),
          json: async () => mockHttpClientService.response.body,
        },
        headers: {},
      };
    });

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    })
      .overrideProvider(GraphApiService)
      .useValue(mockGraphApiService)
      .overrideProvider(SharepointRestClientService)
      .useValue(mockSharepointRestClientService)
      .overrideProvider(HttpClientService)
      .useValue(mockHttpClientService)
      .overrideProvider(IngestionHttpClient)
      .useValue(mockIngestionHttpClient)
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
    capture.clear();
  });

  describe('Content Ingestion', () => {
    describe('when syncing a pdf file', () => {
      it('sends correct mimeType to ContentUpsert', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        // ContentUpsert goes to ingestion service, which may capture multiple operations
        const upserts = capture.getGraphQLOperations('ContentUpsert');
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
      beforeEach(() => {
        const item = mockGraphApiService.items[0];
        if (item && item.itemType === 'driveItem') {
          if (item.item.file) {
            item.item.file.mimeType =
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
          }
          item.item.name = 'report.xlsx';
          item.fileName = 'report.xlsx';
          item.item.listItem.fields.FileLeafRef = 'report.xlsx';
        }
      });

      it('sends correct mimeType to file-diff', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
        expect(fileDiffCalls).toHaveLength(1);

        const requestBody = fileDiffCalls[0]?.body as FileDiffRequest;
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
        const upserts = capture.getGraphQLOperations('ContentUpsert');
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
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalled();
        expect(mockIngestionHttpClient.request).toHaveBeenCalled();
      });
    });

    describe('when file is not marked for sync', () => {
      beforeEach(() => {
        const item = mockGraphApiService.items[0];
        if (item && item.itemType === 'driveItem') {
          item.item.listItem.fields.SyncFlag = false;
        }
      });

      it('excludes file from synchronization', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
        if (fileDiffCalls.length > 0 && fileDiffCalls[0]) {
          expect(fileDiffCalls[0].body).toMatchObject({
            fileList: [],
          });
        }
      });
    });

    describe('when file exceeds size limit', () => {
      beforeEach(() => {
        const item = mockGraphApiService.items[0];
        if (item && item.itemType === 'driveItem') {
          item.item.size = 999999999;
        }
      });

      it('excludes file from file-diff request', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
        if (fileDiffCalls.length > 0 && fileDiffCalls[0]) {
          expect(fileDiffCalls[0].body).toMatchObject({
            fileList: [],
          });
        }
      });
    });

    describe('when multiple files have mixed sync flags', () => {
      beforeEach(() => {
        // Add a second item not marked for sync
        const syncedItem = mockGraphApiService.items[0];
        if (!syncedItem) return;

        const unsyncedItem = JSON.parse(JSON.stringify(syncedItem)) as typeof syncedItem;
        if (unsyncedItem && unsyncedItem.itemType === 'driveItem') {
          unsyncedItem.item.id = 'item-2';
          unsyncedItem.item.name = 'hidden.pdf';
          unsyncedItem.fileName = 'hidden.pdf';
          unsyncedItem.item.listItem.fields.SyncFlag = false;
          unsyncedItem.item.listItem.fields.FileLeafRef = 'hidden.pdf';

          mockGraphApiService.items = [syncedItem, unsyncedItem];
        }
      });

      it('only synchronizes the marked file', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        const fileDiffCalls = capture.getRestCalls('/v2/content/file-diff');
        const requestBody = fileDiffCalls[0]?.body as FileDiffRequest;
        expect(requestBody.fileList).toHaveLength(1);
        expect(requestBody.fileList[0]?.key).toContain('item-1');

        const upserts = capture.getGraphQLOperations('ContentUpsert');
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
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        expect(mockGraphApiService.getDriveItemPermissions).toHaveBeenCalledWith(
          'drive-1',
          'item-1',
        );

        // Verify that CreateFileAccessesForContents was called
        const accessCalls = capture.getGraphQLOperations('CreateFileAccessesForContents');
        expect(accessCalls.length).toBeGreaterThan(0);
      });
    });

    describe('when file has no external permissions', () => {
      beforeEach(() => {
        mockGraphApiService.permissions['item-1'] = [];
      });

      it('still processes the file', async () => {
        const service = app.get(SharepointSynchronizationService);
        await service.synchronize();

        expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalled();
        expect(mockIngestionHttpClient.request).toHaveBeenCalled();
      });
    });
  });

  describe('Integration', () => {
    it('synchronizes content and permissions with mocked dependencies', async () => {
      const service = app.get(SharepointSynchronizationService);
      const result = await service.synchronize();

      expect(result).toEqual({ status: 'success' });

      expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
        '11111111-1111-4111-8111-111111111111',
        'SyncFlag',
      );

      expect(mockIngestionHttpClient.request).toHaveBeenCalled();
      const requests = capture.getAll();
      expect(requests.length).toBeGreaterThan(0);

      expect(mockGraphApiService.getFileContentStream).toHaveBeenCalled();
      expect(mockHttpClientService.request).toHaveBeenCalled();

      expect(mockGraphApiService.getDriveItemPermissions).toHaveBeenCalledWith('drive-1', 'item-1');
    }, 20000);
  });
});
