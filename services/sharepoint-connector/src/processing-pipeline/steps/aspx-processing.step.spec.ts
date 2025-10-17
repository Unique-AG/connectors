import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import type { ListItem } from '../../msgraph/types/sharepoint.types';
import type { ProcessingContext } from '../types/processing-context';
import { AspxProcessingStep } from './aspx-processing.step';

describe('AspxProcessingStep', () => {
  let step: AspxProcessingStep;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(AspxProcessingStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.baseUrl') {
            return 'https://contoso.sharepoint.com';
          }
          return undefined;
        }),
      }))
      .compile();
    step = unit;
  });

  const createContext = (overrides: Partial<ProcessingContext> = {}): ProcessingContext => ({
    correlationId: 'c1',
    startTime: new Date(),
    knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/test/test.aspx',
    mimeType: 'application/octet-stream',
    pipelineItem: {
      itemType: 'listItem',
      item: {
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
      } as ListItem,
      siteId: 'site-1',
      siteWebUrl: 'https://contoso.sharepoint.com',
      driveId: 'drive-1',
      driveName: 'SitePages',
      folderPath: '/',
      fileName: 'test.aspx',
    },
    ...overrides,
  });

  it('passes through non-listItem files unchanged', async () => {
    const context = createContext({
      pipelineItem: {
        ...createContext().pipelineItem,
        itemType: 'driveItem' as const,
      },
    });
    const result = await step.execute(context);
    expect(result).toBe(context);
  });

  it('processes ASPX files with content', async () => {
    const context = createContext({
      contentBuffer: Buffer.from('<p>Test content</p>', 'utf-8'),
    });

    const result = await step.execute(context);

    expect(result.mimeType).toBe('text/html');
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Test Page</h2>');
    expect(html).toContain('<h4>Test User</h4>');
    expect(html).toContain('<p>Test content</p>');
  });

  it('falls back to filename when Title is missing', async () => {
    const context = createContext({
      pipelineItem: {
        ...createContext().pipelineItem,
        item: {
          ...createContext().pipelineItem.item,
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            _ModerationStatus: ModerationStatus.Approved,
            FileSizeDisplay: '512',
            FileLeafRef: 'test.aspx',
          },
        } as ListItem,
      },
      contentBuffer: Buffer.from('<p>Content</p>', 'utf-8'),
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>test.aspx</h2>');
  });

  it('handles missing author information', async () => {
    const context = createContext({
      pipelineItem: {
        ...createContext().pipelineItem,
        item: {
          ...createContext().pipelineItem.item,
          createdBy: {
            user: {
              email: '',
              id: '',
              displayName: '',
            },
          },
        } as ListItem,
      },
      contentBuffer: Buffer.from('<p>Content</p>', 'utf-8'),
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Test Page</h2>');
    expect(html).toContain('<h4></h4>');
    expect(html).toContain('<p>Content</p>');
  });

  it('handles partial author information', async () => {
    const context = createContext({
      pipelineItem: {
        ...createContext().pipelineItem,
        item: {
          ...createContext().pipelineItem.item,
          createdBy: {
            user: {
              email: 'john@example.com',
              id: 'user2',
              displayName: 'John',
            },
          },
        } as ListItem,
      },
      contentBuffer: Buffer.from('<p>Content</p>', 'utf-8'),
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h4>John</h4>');
  });

  it('converts relative links to absolute links', () => {
    const convertRelativeLinks = (content: string, baseUrl: string): string => {
      if (!content || !baseUrl) {
        return content;
      }
      return content.replace(/href="\/(.*?)"/g, `href="${baseUrl}$1"`);
    };

    const input = '<a href="/sites/test/page.aspx">Link</a><img src="/sites/test/image.png">';
    const baseUrl = 'https://contoso.sharepoint.com';

    const result = convertRelativeLinks(input, baseUrl);

    expect(result).toBe(
      '<a href="https://contoso.sharepoint.comsites/test/page.aspx">Link</a><img src="/sites/test/image.png">',
    );
  });

  it('handles empty content', async () => {
    const context = createContext({
      contentBuffer: undefined,
    });

    const result = await step.execute(context);
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Test Page</h2>');
    expect(html).toContain('<div>');
    expect(html).toContain('</div>');
  });

  it('handles case insensitive ASPX detection for listItems', async () => {
    const context = createContext({
      pipelineItem: {
        ...createContext().pipelineItem,
        fileName: 'Test.ASPX',
      },
      contentBuffer: Buffer.from('<p>Content</p>', 'utf-8'),
    });

    const result = await step.execute(context);
    expect(result.mimeType).toBe('text/html');
    const html = result.contentBuffer?.toString();
    expect(html).toContain('<h2>Test Page</h2>');
  });
});
