import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import type { ListItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import type { ProcessingContext } from '../types/processing-context';
import { AspxProcessingStep } from './aspx-processing.step';

describe('AspxProcessingStep', () => {
  let step: AspxProcessingStep;
  let mockConfigService: {
    get: ReturnType<typeof vi.fn>;
  };

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
    correlationId: 'c1',
    startTime: new Date(),
    knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/test/test.aspx',
    mimeType: 'application/octet-stream',
    scopeId: 'scope-1',
    fileStatus: 'new',
    currentUserId: 'user-1',
    pipelineItem: {
      itemType: 'listItem' as const,
      item: mockListItem,
      siteId: 'site-1',
      siteWebUrl: 'https://contoso.sharepoint.com',
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

    const { unit } = await TestBed.solitary(AspxProcessingStep)
      .mock(ConfigService)
      .impl(() => mockConfigService)
      .compile();

    step = unit;
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
    });

    it('processes listItem and returns context with HTML content', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<p>Test content</p>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      expect(result.mimeType).toBe('text/html');
      expect(result.contentBuffer).toBeDefined();
      const html = result.contentBuffer?.toString();
      expect(html).toContain('<h2>Test Page</h2>');
      expect(html).toContain('<h4>Test User</h4>');
      expect(html).toContain('<p>Test content</p>');
    });

    it('wraps HTML content in proper structure', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<p>Test</p>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toMatch(/^<div>.*<\/div>$/);
      expect(html).toContain('<h2>Test Page</h2>');
      expect(html).toContain('<h4>Test User</h4>');
    });

    it('converts relative links to absolute links', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<a href="/sites/test/page.aspx">Link</a>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain(
        '<a href="https://contoso.sharepoint.com/sites/test/page.aspx">Link</a>',
      );
    });

    it('converts multiple relative links in same content', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from(
          '<a href="/page1.aspx">Link 1</a><a href="/page2.aspx">Link 2</a>',
          'utf-8',
        ),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<a href="https://contoso.sharepoint.com/page1.aspx">Link 1</a>');
      expect(html).toContain('<a href="https://contoso.sharepoint.com/page2.aspx">Link 2</a>');
    });

    it('handles links with query parameters', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<a href="/page.aspx?id=123&type=test">Link</a>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain(
        '<a href="https://contoso.sharepoint.com/page.aspx?id=123&type=test">Link</a>',
      );
    });

    it('handles links with fragments', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<a href="/page.aspx#section">Link</a>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<a href="https://contoso.sharepoint.com/page.aspx#section">Link</a>');
    });

    it('does not convert non-href attributes', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<img src="/sites/test/image.png">', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<img src="/sites/test/image.png">');
    });

    it('preserves absolute links', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<a href="https://external.com/page">External</a>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<a href="https://external.com/page">External</a>');
    });

    it('handles deeply nested relative paths', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from(
          '<a href="/sites/team/docs/subfolder/document.aspx">Link</a>',
          'utf-8',
        ),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain(
        '<a href="https://contoso.sharepoint.com/sites/team/docs/subfolder/document.aspx">Link</a>',
      );
    });

    it('handles empty href values', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<a href="">Empty Link</a>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<a href="">Empty Link</a>');
    });

    it('handles mixed relative and absolute links', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from(
          '<a href="/relative.aspx">Relative</a><a href="https://absolute.com">Absolute</a>',
          'utf-8',
        ),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<a href="https://contoso.sharepoint.com/relative.aspx">Relative</a>');
      expect(html).toContain('<a href="https://absolute.com">Absolute</a>');
    });

    it('handles baseUrl without trailing slash correctly', async () => {
      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<a href="/page.aspx">Link</a>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<a href="https://contoso.sharepoint.com/page.aspx">Link</a>');
    });

    it('handles context with missing contentBuffer', async () => {
      const contextWithoutContent = { ...mockContext };

      const result = await step.execute(contextWithoutContent);

      expect(result.mimeType).toBe('text/html');
      const html = result.contentBuffer?.toString();
      expect(html).toContain('<h2>Test Page</h2>');
      expect(html).toContain('<h4>Test User</h4>');
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
              Title: '', // Empty title will fallback to filename
              FileSizeDisplay: '512',
              FileLeafRef: 'test.aspx',
            },
          },
        },
        contentBuffer: Buffer.from('<p>Content</p>', 'utf-8'),
      } as ProcessingContext;

      const result = await step.execute(contextWithMissingTitle);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<h2>test.aspx</h2>');
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
        contentBuffer: Buffer.from('<p>Content</p>', 'utf-8'),
      } as ProcessingContext;

      const result = await step.execute(contextWithEmptyAuthor);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<h4></h4>');
    });

    it('normalizes baseUrl with trailing slash before converting links', async () => {
      mockConfigService.get.mockImplementation((key: string) => {
        if (key === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com/';
        return undefined;
      });

      const contextWithContent = {
        ...mockContext,
        contentBuffer: Buffer.from('<a href="/sites/test">Link</a>', 'utf-8'),
      };

      const result = await step.execute(contextWithContent);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<a href="https://contoso.sharepoint.com/sites/test">Link</a>');
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
        contentBuffer: Buffer.from('<p>Content</p>', 'utf-8'),
      } as ProcessingContext;

      const result = await step.execute(contextWithNullCreatedBy);

      const html = result.contentBuffer?.toString();
      expect(html).toContain('<h4>unknown-author</h4>');
    });
  });
});
