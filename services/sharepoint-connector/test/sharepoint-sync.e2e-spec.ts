import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { MockAgent } from 'undici';
import { AppModule } from '../src/app.module';
import { SchedulerService } from '../src/scheduler/scheduler.service';
import { SharepointSynchronizationService } from '../src/sharepoint-synchronization/sharepoint-synchronization.service';
import { IngestionHttpClient } from '../src/unique-api/clients/ingestion-http.client';
import { HttpClientService } from '../src/shared/services/http-client.service';
import { MicrosoftAuthenticationService } from '../src/microsoft-apis/auth/microsoft-authentication.service';
import { FakeUniqueRegistry } from './test-utils/fake-unique-registry';
import { 
  setupMockAgent, 
  mockGraphAuth, 
  mockUniqueAuth, 
  mockUniqueIngestion, 
  mockUniqueScopeManagement,
  mockGraphApi,
  MockGraphState
} from './test-utils/mock-agent.helpers';
import { createDriveItem, createPermission, createPageItem } from './test-utils/graph-fixtures';

describe('SharePoint synchronization (Senior E2E)', () => {
  let app: INestApplication;
  let agent: MockAgent;
  let registry: FakeUniqueRegistry;
  let graphState: MockGraphState;

  beforeEach(async () => {
    registry = new FakeUniqueRegistry();
    agent = setupMockAgent();
    
    // Default mocks for Auth
    mockGraphAuth(agent);
    mockUniqueAuth(agent, 'https://auth.test.example.com/oauth/token');
    
    // Mocks for Unique Services backed by FakeRegistry
    mockUniqueIngestion(agent, 'https://unique-ingestion.test', registry);
    mockUniqueScopeManagement(agent, 'https://unique-scope.test', registry);

    // Initial MS Graph State
    graphState = {
      drives: [{ id: 'drive-1', name: 'Documents' }],
      itemsByDrive: {
        'drive-1': [createDriveItem('item-1', 'test.pdf')]
      },
      permissionsByItem: {
        'item-1': [createPermission('perm-1', 'user@example.com')]
      },
      siteLists: [
        { id: 'sitepages-id', name: 'SitePages', displayName: 'Site Pages' }
      ],
      listItems: { 
        'sitepages-id': [] 
      },
      pageContent: {}
    };
    mockGraphApi(agent, graphState);

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    })
      .overrideProvider(SchedulerService)
      .useValue({
        onModuleInit: () => {},
        onModuleDestroy: () => {},
      })
      .overrideProvider(MicrosoftAuthenticationService)
      .useValue({
        getAccessToken: () => Promise.resolve('fake-token'),
      })
      .compile();

    app = moduleFixture.createNestApplication();
    await app.init();

    // Inject MockAgent into services that bypass global dispatcher
    const ingestionHttpClient = app.get(IngestionHttpClient);
    (ingestionHttpClient as any).httpClient = agent.get('https://unique-ingestion.test');

    const httpClientService = app.get(HttpClientService);
    (httpClientService as any).httpAgent = agent;
  });

  afterEach(async () => {
    // Prevent the services from closing our MockAgent during app.close()
    if (app) {
      const ingestionHttpClient = app.get(IngestionHttpClient);
      (ingestionHttpClient as any).httpClient = { close: () => Promise.resolve() };
      const httpClientService = app.get(HttpClientService);
      (httpClientService as any).httpAgent = { close: () => Promise.resolve() };
      
      await app.close();
    }
    if (agent) await agent.close();
  });

  describe('Core Synchronization Logic', () => {
    it('successfully ingests a new file and registers permissions in the registry', async () => {
      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      const ingested = registry.getFileBySpId('item-1');
      expect(ingested).toBeDefined();
      expect(ingested?.title).toBe('test.pdf');
      // id-perm-1 is the Unique user ID mapped from user@example.com
      expect(ingested?.access).toContain('u:id-perm-1R');
    }, 30000);

    it('updates existing content when modified in SharePoint', async () => {
      // 1. Initial sync
      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();
      const ingestedAtFirst = registry.getFileBySpId('item-1');
      const firstId = ingestedAtFirst?.id;

      // 2. Modify file in SharePoint (update timestamp and size)
      const item = graphState.itemsByDrive['drive-1'][0];
      item.size = 2048;
      item.lastModifiedDateTime = new Date(Date.now() + 10000).toISOString();
      item.listItem.fields.Modified = item.lastModifiedDateTime;

      await service.synchronize();

      const ingestedAtSecond = registry.getFileBySpId('item-1');
      expect(ingestedAtSecond?.id).toBe(firstId); // same content ID
      expect(ingestedAtSecond?.byteSize).toBe(2048);
    }, 30000);

    it('handles file deletions in SharePoint by removing them from Unique', async () => {
      // 1. Initial sync with 2 files
      graphState.itemsByDrive['drive-1'].push(createDriveItem('item-2', 'second.pdf'));
      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();
      expect(registry.getFiles()).toHaveLength(2);

      // 2. Remove 1 file from SharePoint
      graphState.itemsByDrive['drive-1'] = [
        graphState.itemsByDrive['drive-1'][0]
      ];

      await service.synchronize();

      expect(registry.getFiles()).toHaveLength(1);
      expect(registry.getFileBySpId('item-2')).toBeUndefined();
    }, 30000);

    it('respects SyncFlag and excludes files not marked for sync', async () => {
      graphState.itemsByDrive['drive-1'].push(
        createDriveItem('item-2', 'hidden.pdf', { syncFlag: false })
      );

      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      expect(registry.getFileBySpId('item-1')).toBeDefined();
      expect(registry.getFileBySpId('item-2')).toBeUndefined();
    }, 30000);
  });

  describe('Complex Scenarios & Resiliency', () => {
    it('syncs mixed user and group permissions correctly', async () => {
      graphState.permissionsByItem['item-1'] = [
        createPermission('perm-1', 'user@example.com', 'user'),
        createPermission('group-perm', 'Finance Group', 'group'),
      ];

      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      const ingested = registry.getFileBySpId('item-1');
      // id-perm-1 and id-group-perm are the Unique IDs from our mocks
      expect(ingested?.access).toContain('u:id-perm-1R');
      expect(ingested?.access).toContain('g:id-group-permR');
    }, 30000);

    it('retries successfully when MS Graph returns 429 (Rate Limited)', async () => {
      const graphClient = agent.get('https://graph.microsoft.com');
      graphClient
        .intercept({
          path: (p) => p.includes('/drives'),
          method: 'GET',
        })
        .reply(429, {}, { 
          headers: { 'Retry-After': '1', 'content-type': 'application/json' } 
        });

      const service = app.get(SharepointSynchronizationService);
      const result = await service.synchronize();

      expect(result.status).toBe('success');
      expect(registry.getFileBySpId('item-1')).toBeDefined();
    }, 30000);

    it('correctly ingests SharePoint Site Pages (ASPX)', async () => {
      const pageId = 'page-123';
      graphState.listItems['sitepages-id'] = [
        createPageItem(pageId, 'Welcome Page')
      ];
      graphState.pageContent[pageId] = {
        fields: {
          Title: 'Welcome Page',
          CanvasContent1: '<h1>Hello World</h1>',
        }
      };

      const service = app.get(SharepointSynchronizationService);
      await service.synchronize();

      const page = registry.getFiles().find(f => f.title === 'Welcome Page');
      expect(page).toBeDefined();
      expect(page?.mimeType).toBe('text/html');
    }, 30000);

    it('continues synchronization even if one drive fails', async () => {
      graphState.drives.push({ id: 'drive-fail', name: 'Failing Drive' });
      
      const graphClient = agent.get('https://graph.microsoft.com');
      graphClient
        .intercept({
          path: (p) => p.includes('/drives/drive-fail'),
          method: 'GET',
        })
        .reply(500, JSON.stringify({ error: { message: 'Internal Server Error' } }), { headers: { 'content-type': 'application/json' } });

      const service = app.get(SharepointSynchronizationService);
      const result = await service.synchronize();

      expect(result.status).toBe('success');
      expect(registry.getFileBySpId('item-1')).toBeDefined();
    }, 30000);
  });
});
