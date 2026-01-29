import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import { GraphApiService } from '../../microsoft-apis/graph/graph-api.service';
import type { ListItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import { createSmeared } from '../../utils/smeared';
import { createMockSiteConfig } from '../../utils/test-utils/mock-site-config';
import type { ProcessingContext } from '../types/processing-context';
import { AspxProcessingStep } from './aspx-processing.step';

describe('AspxProcessingStep', () => {
  let step: AspxProcessingStep;
  let mockConfigService: {
    get: ReturnType<typeof vi.fn>;
  };
  let mockApiService: GraphApiService;

  const mockListItem: ListItem = {
    id: 'f1',
    webUrl: 'https://contoso.sharepoint.com/sites/test/test.aspx',
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
    createdDateTime: '2024-01-01T00:00:00Z',
    createdBy: {
      user: {
        email: 'test@example.com',
        id: 'user1',
        displayName: 'Test User',
      },
    },
    fields: {
      '@odata.etag': 'etag1',
      FinanceGPTKnowledge: false,
      _ModerationStatus: ModerationStatus.Approved,
      Title: 'Test Page',
      FileSizeDisplay: '512',
      FileLeafRef: 'test.aspx',
    },
  };

  const mockContext: ProcessingContext = {
    syncContext: {
      siteConfig: createMockSiteConfig(),
      siteName: 'test-site',
      serviceUserId: 'user-1',
      rootPath: '/Root',
    },
    correlationId: 'c1',
    startTime: new Date(),
    knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/test/test.aspx',
    mimeType: 'application/octet-stream',
    targetScopeId: 'scope-1', // forced save
    fileStatus: 'new',
    pipelineItem: {
      itemType: 'listItem' as const,
      item: mockListItem,
      siteId: createSmeared('site-1'),
      driveId: 'drive-1',
      driveName: 'SitePages',
      folderPath: '/',
      fileName: 'test.aspx',
    } as const,
  };

  beforeEach(async () => {
    mockConfigService = {
      get: vi.fn((key: string) => {
        if (key === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com';
        return undefined;
      }),
    };

    const { unit, unitRef } = await TestBed.solitary(AspxProcessingStep)
      .mock(ConfigService)
      .impl(() => mockConfigService)
      .mock(GraphApiService)
      .impl((stub) => ({
        ...stub(),
        getAspxPageContent: vi.fn().mockResolvedValue({
          canvasContent: '<p>Test content</p>',
          wikiField: undefined,
          title: 'Test Page',
        }),
      }))
      .compile();

    step = unit;
    mockApiService = unitRef.get(GraphApiService) as unknown as GraphApiService;
  });

  describe('execute', () => {
    it('returns context unchanged for non-listItem files', async () => {
      const contextWithDriveItem = {
        ...mockContext,
        pipelineItem: {
          ...mockContext.pipelineItem,
          itemType: 'driveItem' as const,
          item: mockContext.pipelineItem.item,
        },
      } as ProcessingContext;

      const result = await step.execute(contextWithDriveItem);

      expect(result).toBe(contextWithDriveItem);
      expect(mockApiService.getAspxPageContent).not.toHaveBeenCalled();
    });

    it('fetches ASPX content and returns context with HTML content', async () => {
      const result = await step.execute(mockContext);

      expect(mockApiService.getAspxPageContent).toHaveBeenCalledWith(
        expect.objectContaining({ value: 'site-1' }),
        'drive-1',
        'f1',
      );
      expect(result.mimeType).toBe('text/html');
      expect(result.htmlContent).toBeDefined();
      expect(result.htmlContent).toContain('<h2>Test Page</h2>');
      expect(result.htmlContent).toContain('<h4>Test User</h4>');
      expect(result.htmlContent).toContain('<p>Test content</p>');
    });

    it('wraps HTML content in proper structure', async () => {
      const result = await step.execute(mockContext);

      expect(result.htmlContent).toMatch(/^<div>.*<\/div>$/);
      expect(result.htmlContent).toContain('<h2>Test Page</h2>');
      expect(result.htmlContent).toContain('<h4>Test User</h4>');
    });

    it('converts relative links to absolute links', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="/sites/test/page.aspx">Link</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/sites/test/page.aspx">Link</a>',
      );
    });

    it('converts multiple relative links in same content', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="/page1.aspx">Link 1</a><a href="/page2.aspx">Link 2</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/page1.aspx">Link 1</a>',
      );
      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/page2.aspx">Link 2</a>',
      );
    });

    it('handles links with query parameters', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="/page.aspx?id=123&type=test">Link</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/page.aspx?id=123&type=test">Link</a>',
      );
    });

    it('handles links with fragments', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="/page.aspx#section">Link</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/page.aspx#section">Link</a>',
      );
    });

    it('does not convert non-href attributes', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<img src="/sites/test/image.png">',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain('<img src="/sites/test/image.png">');
    });

    it('preserves absolute links', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="https://external.com/page">External</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain('<a href="https://external.com/page">External</a>');
    });

    it('handles deeply nested relative paths', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="/sites/team/docs/subfolder/document.aspx">Link</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/sites/team/docs/subfolder/document.aspx">Link</a>',
      );
    });

    it('handles empty href values', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="">Empty Link</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain('<a href="">Empty Link</a>');
    });

    it('handles mixed relative and absolute links', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent:
          '<a href="/relative.aspx">Relative</a><a href="https://absolute.com">Absolute</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/relative.aspx">Relative</a>',
      );
      expect(result.htmlContent).toContain('<a href="https://absolute.com">Absolute</a>');
    });

    it('handles baseUrl without trailing slash correctly', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="/page.aspx">Link</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/page.aspx">Link</a>',
      );
    });

    it('handles empty content from API', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: undefined,
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.mimeType).toBe('text/html');
      expect(result.htmlContent).toContain('<h2>Test Page</h2>');
      expect(result.htmlContent).toContain('<h4>Test User</h4>');
    });

    it('uses wikiField when canvasContent is undefined', async () => {
      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: undefined,
        wikiField: '<p>Wiki content</p>',
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain('<p>Wiki content</p>');
    });

    it('uses filename when Title field is missing', async () => {
      const contextWithMissingTitle = {
        ...mockContext,
        pipelineItem: {
          ...mockContext.pipelineItem,
          item: {
            ...mockListItem,
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              _ModerationStatus: ModerationStatus.Approved,
              Title: '',
              FileSizeDisplay: '512',
              FileLeafRef: 'test.aspx',
            },
          },
        },
      } as ProcessingContext;

      const result = await step.execute(contextWithMissingTitle);

      expect(result.htmlContent).toContain('<h2>test.aspx</h2>');
    });

    it('handles empty author displayName', async () => {
      const contextWithEmptyAuthor = {
        ...mockContext,
        pipelineItem: {
          ...mockContext.pipelineItem,
          item: {
            ...mockListItem,
            createdBy: {
              user: { email: '', id: '', displayName: '' },
            },
          },
        },
      } as ProcessingContext;

      const result = await step.execute(contextWithEmptyAuthor);

      expect(result.htmlContent).toContain('<h4></h4>');
    });

    it('normalizes baseUrl with trailing slash before converting links', async () => {
      mockConfigService.get.mockImplementation((key: string) => {
        if (key === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com/';
        return undefined;
      });

      vi.mocked(mockApiService.getAspxPageContent).mockResolvedValue({
        canvasContent: '<a href="/sites/test">Link</a>',
        wikiField: undefined,
        title: 'Test',
      });

      const result = await step.execute(mockContext);

      expect(result.htmlContent).toContain(
        '<a href="https://contoso.sharepoint.com/sites/test">Link</a>',
      );
    });

    it('handles null author createdBy', async () => {
      const contextWithNullCreatedBy = {
        ...mockContext,
        pipelineItem: {
          ...mockContext.pipelineItem,
          item: {
            ...mockListItem,
            createdBy: null as unknown as ListItem['createdBy'],
          },
        },
      } as ProcessingContext;

      const result = await step.execute(contextWithNullCreatedBy);

      expect(result.htmlContent).toContain('<h4>unknown-author</h4>');
    });

    it('sets correct fileSize based on HTML content byte length', async () => {
      const result = await step.execute(mockContext);

      expect(result.fileSize).toBe(Buffer.byteLength(result.htmlContent ?? '', 'utf-8'));
    });
  });
});
