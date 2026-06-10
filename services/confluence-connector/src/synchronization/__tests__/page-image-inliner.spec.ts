import { Readable } from 'node:stream';
import { Smeared } from '@unique-ag/utils';
import { createMock } from '@golevelup/ts-vitest';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TenantConfig } from '../../config';
import type { ConfluenceApiClient, ConfluenceAttachment } from '../../confluence-api';
import {
  CONFLUENCE_BASE_URL,
  PAGE_BODY_EXTERNAL_URL_IMAGE,
  PAGE_BODY_IMAGE_NESTED_IN_TABLE,
  PAGE_BODY_IMAGE_WITH_ATTRS,
  PAGE_BODY_MIXED_URL_AND_ATTACHMENT,
  PAGE_BODY_MULTIPLE_CURRENT_PAGE_IMAGES,
  PAGE_BODY_OTHER_PAGE_IMAGE,
  PAGE_BODY_SELF_CLOSING_IMAGE,
  PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE,
  PAGE_BODY_TWO_REFERENCES_SAME_OTHER_PAGE,
  PAGE_BODY_UNCLOSED_IMAGE,
  PAGE_BODY_WITH_CDATA_AND_IMAGE,
  sampleDiscoveredImageAttachment,
  sampleDiscoveredPdfAttachment,
} from '../__mocks__/sync.fixtures';
import { buildInlinedAttachmentKey, PageImageInliner } from '../page-image-inliner';
import type { DiscoveredAttachment, FetchedPage } from '../sync.types';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => mockLogger),
  };
});

function createTestTenantConfig(
  overrides: { maxFileSizeMb?: number; allowedMimeTypes?: string[] } = {},
): TenantConfig {
  return createMock<TenantConfig>({
    ingestion: {
      attachments: {
        maxFileSizeMb: overrides.maxFileSizeMb ?? 200,
        allowedMimeTypes: overrides.allowedMimeTypes ?? [
          'image/png',
          'image/jpeg',
          'application/pdf',
        ],
      },
    },
  });
}

const baseTenantConfig: TenantConfig = createTestTenantConfig();

function basePage(body: string): FetchedPage {
  return {
    id: '1',
    title: new Smeared('Page 1', false),
    body,
    webUrl: `${CONFLUENCE_BASE_URL}/page/1`,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
  };
}

function imageBuffer(content = 'PNGDATA'): Buffer {
  return Buffer.from(content);
}

function createConfluenceImageAttachment(
  overrides: Partial<{
    id: string;
    title: string;
    mediaType: string;
    fileSize: number;
    download: string;
  }> = {},
): ConfluenceAttachment {
  return {
    id: overrides.id ?? 'remote-att-1',
    title: overrides.title ?? 'other.png',
    extensions: {
      mediaType: overrides.mediaType ?? 'image/png',
      fileSize: overrides.fileSize ?? 1024,
    },
    _links: { download: overrides.download ?? '/download/attachments/77/other.png' },
  };
}

describe('PageImageInliner', () => {
  let apiClient: ReturnType<typeof createMock<ConfluenceApiClient>>;
  let inliner: PageImageInliner;

  beforeEach(() => {
    vi.clearAllMocks();
    apiClient = createMock<ConfluenceApiClient>();
    inliner = new PageImageInliner(baseTenantConfig, apiClient);
  });

  describe('no-op cases', () => {
    it('returns the page unchanged when body is empty', async () => {
      const page = basePage('');
      const result = await inliner.inlineImages(page, []);
      expect(result.page).toBe(page);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('returns the page unchanged when no <ac:image> macros are present', async () => {
      const page = basePage('<p>just text</p>');
      const result = await inliner.inlineImages(page, []);
      expect(result.page).toBe(page);
      expect(result.inlinedAttachmentIds.size).toBe(0);
    });
  });

  describe('current-page attachment inlining', () => {
    it('replaces a single <ac:image> with <img src="data:...;base64,...">', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);

      const result = await inliner.inlineImages(page, [sampleDiscoveredImageAttachment]);

      const expectedBase64 = imageBuffer().toString('base64');
      expect(result.page.body).toContain(`src="data:image/png;base64,${expectedBase64}"`);
      expect(result.page.body).not.toContain('<ac:image');
      expect(result.page.body.startsWith('<p>before</p>')).toBe(true);
      expect(result.page.body.endsWith('<p>after</p>')).toBe(true);
      expect(
        result.inlinedAttachmentIds.has(
          buildInlinedAttachmentKey(
            sampleDiscoveredImageAttachment.pageId,
            sampleDiscoveredImageAttachment.id,
          ),
        ),
      ).toBe(true);
    });

    it('preserves byte-perfect surroundings of the swapped block', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_WITH_CDATA_AND_IMAGE);

      const result = await inliner.inlineImages(page, [sampleDiscoveredImageAttachment]);

      expect(result.page.body).toContain(
        '<ac:plain-text-body><![CDATA[const x = "<not a tag>" & 1 < 2;]]></ac:plain-text-body>',
      );
      expect(result.page.body).not.toContain('<ac:image');
    });

    it('replaces multiple images, each with its own data URI', async () => {
      apiClient.getAttachmentDownloadStream
        .mockResolvedValueOnce(Readable.from(Buffer.from('one')))
        .mockResolvedValueOnce(Readable.from(Buffer.from('two')));
      const oneAtt: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        id: 'att-one',
        title: 'one.png',
        mediaType: 'image/png',
        downloadPath: '/download/attachments/1/one.png',
      };
      const twoAtt: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        id: 'att-two',
        title: 'two.jpg',
        mediaType: 'image/jpeg',
        downloadPath: '/download/attachments/1/two.jpg',
      };

      const result = await inliner.inlineImages(basePage(PAGE_BODY_MULTIPLE_CURRENT_PAGE_IMAGES), [
        oneAtt,
        twoAtt,
      ]);

      expect(result.page.body).toContain(
        `src="data:image/png;base64,${Buffer.from('one').toString('base64')}"`,
      );
      expect(result.page.body).toContain(
        `src="data:image/jpeg;base64,${Buffer.from('two').toString('base64')}"`,
      );
      expect(result.page.body).not.toContain('<ac:image');
      expect(result.inlinedAttachmentIds).toEqual(
        new Set([
          buildInlinedAttachmentKey('1', 'att-one'),
          buildInlinedAttachmentKey('1', 'att-two'),
        ]),
      );
    });

    it('maps ac:alt, ac:title, ac:width, ac:height onto the produced <img>', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const result = await inliner.inlineImages(basePage(PAGE_BODY_IMAGE_WITH_ATTRS), [
        sampleDiscoveredImageAttachment,
      ]);

      expect(result.page.body).toMatch(/<img\s[^>]*\balt="An alt"/);
      expect(result.page.body).toMatch(/<img\s[^>]*\btitle="A title"/);
      expect(result.page.body).toMatch(/<img\s[^>]*\bwidth="320"/);
      expect(result.page.body).toMatch(/<img\s[^>]*\bheight="240"/);
      expect(result.page.body).not.toMatch(/ac:align="center"/);
      expect(result.page.body).not.toMatch(/\balign="center"/);
      expect(result.page.body).not.toMatch(/\bthumbnail=/);
    });
  });

  describe('skip / fallback cases', () => {
    it('leaves <ac:image> untouched when the filename is not among page attachments', async () => {
      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);
      const result = await inliner.inlineImages(page, []);
      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves <ac:image> untouched when the matching attachment is not image/*', async () => {
      const page = basePage('<ac:image><ri:attachment ri:filename="spec.pdf"/></ac:image>');
      const result = await inliner.inlineImages(page, [sampleDiscoveredPdfAttachment]);
      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves <ac:image> untouched when the attachment exceeds maxFileSizeMb', async () => {
      const oversize: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        fileSize: 5 * 1024 * 1024,
      };
      const smallLimitInliner = new PageImageInliner(
        createTestTenantConfig({ maxFileSizeMb: 1 }),
        apiClient,
      );
      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);
      const result = await smallLimitInliner.inlineImages(page, [oversize]);
      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves <ac:image> untouched when the download stream errors', async () => {
      const failingStream = new Readable({
        read() {
          this.destroy(new Error('download failed'));
        },
      });
      apiClient.getAttachmentDownloadStream.mockResolvedValue(failingStream);

      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);
      const result = await inliner.inlineImages(page, [sampleDiscoveredImageAttachment]);

      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
    });

    it('leaves <ac:image> untouched when the matching attachment is an image/* type that is not in allowedMimeTypes', async () => {
      // A current-page reference resolving to image/gif is dropped even though the
      // attachment exists. Defensive in case discovery ever produces a non-allowlisted
      // image type (today the scanner already filters by allowedMimeTypes).
      const gifAttachment: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        mediaType: 'image/gif',
      };
      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);
      const result = await inliner.inlineImages(page, [gifAttachment]);
      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves <ri:url> external images untouched and never fetches them', async () => {
      const page = basePage(PAGE_BODY_EXTERNAL_URL_IMAGE);
      const result = await inliner.inlineImages(page, []);
      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
      expect(apiClient.fetchAttachmentsByPageTitle).not.toHaveBeenCalled();
    });
  });

  describe('other-page attachment resolution', () => {
    it('resolves an <ri:attachment> on another page via fetchAttachmentsByPageTitle and inlines it', async () => {
      const remoteAttachment = createConfluenceImageAttachment({
        id: 'remote-att-1',
        title: 'other.png',
        mediaType: 'image/png',
      });
      const lookup = {
        pageId: '77',
        attachments: [remoteAttachment],
      };
      apiClient.fetchAttachmentsByPageTitle.mockResolvedValue(lookup);
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));

      const page = basePage(PAGE_BODY_OTHER_PAGE_IMAGE);
      const result = await inliner.inlineImages(page, []);

      expect(apiClient.fetchAttachmentsByPageTitle).toHaveBeenCalledWith('OTHER', 'Other Page');
      expect(apiClient.fetchAttachmentsByPageTitle).toHaveBeenCalledTimes(1);
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledWith(
        'remote-att-1',
        '77',
        '/download/attachments/77/other.png',
      );
      expect(result.page.body).toContain(
        `src="data:image/png;base64,${imageBuffer().toString('base64')}"`,
      );
      expect(result.inlinedAttachmentIds.has(buildInlinedAttachmentKey('77', 'remote-att-1'))).toBe(
        true,
      );
    });

    it('inlines both images when a page references the same other-page twice', async () => {
      const remoteA = createConfluenceImageAttachment({
        id: 'remote-a',
        title: 'a.png',
      });
      const remoteB = createConfluenceImageAttachment({
        id: 'remote-b',
        title: 'b.png',
      });
      apiClient.fetchAttachmentsByPageTitle.mockResolvedValue({
        pageId: '77',
        attachments: [remoteA, remoteB],
      });
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));

      const result = await inliner.inlineImages(
        basePage(PAGE_BODY_TWO_REFERENCES_SAME_OTHER_PAGE),
        [],
      );

      // No lookup cache: each reference fetches the referenced page's attachments independently.
      expect(apiClient.fetchAttachmentsByPageTitle).toHaveBeenCalledTimes(2);
      expect(result.inlinedAttachmentIds).toEqual(
        new Set([
          buildInlinedAttachmentKey('77', 'remote-a'),
          buildInlinedAttachmentKey('77', 'remote-b'),
        ]),
      );
    });

    it('leaves an other-page macro untouched when the resolved attachment is an image type outside allowedMimeTypes', async () => {
      // Attachment lookups against a referenced other page return raw Confluence
      // metadata that has not been filtered by discovery. A GIF/WebP/SVG on the
      // referenced page must be rejected by the inliner so it doesn't end up
      // base64-embedded into the page.
      apiClient.fetchAttachmentsByPageTitle.mockResolvedValue({
        pageId: '77',
        attachments: [
          createConfluenceImageAttachment({
            id: 'remote-gif',
            title: 'other.png',
            mediaType: 'image/gif',
          }),
        ],
      });

      const page = basePage(PAGE_BODY_OTHER_PAGE_IMAGE);
      const result = await inliner.inlineImages(page, []);

      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves an other-page macro untouched when the referenced page is not found', async () => {
      apiClient.fetchAttachmentsByPageTitle.mockResolvedValue(null);

      const page = basePage(PAGE_BODY_OTHER_PAGE_IMAGE);
      const result = await inliner.inlineImages(page, []);

      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves macro untouched when <ri:page> is present but missing required attrs (does not silently fall back to current-page)', async () => {
      // A malformed <ri:page> (missing ri:space-key or ri:content-title) must NOT be
      // treated as a current-page attachment, even if the current page happens to have
      // an attachment with the same filename. The presence of <ri:page> signals
      // intent to reference an attachment on another page; we'd rather skip than
      // inline the wrong image.
      const samePageDecoy: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        title: 'other.png',
      };
      const bodyMissingSpaceKey =
        '<ac:image><ri:attachment ri:filename="other.png"><ri:page ri:content-title="Other Page"/></ri:attachment></ac:image>';
      const bodyMissingContentTitle =
        '<ac:image><ri:attachment ri:filename="other.png"><ri:page ri:space-key="OTHER"/></ri:attachment></ac:image>';

      for (const body of [bodyMissingSpaceKey, bodyMissingContentTitle]) {
        vi.clearAllMocks();
        const result = await inliner.inlineImages(basePage(body), [samePageDecoy]);
        expect(result.page.body).toBe(body);
        expect(result.inlinedAttachmentIds.size).toBe(0);
        expect(apiClient.fetchAttachmentsByPageTitle).not.toHaveBeenCalled();
        expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
      }
    });

    it('leaves an other-page macro untouched when fetchAttachmentsByPageTitle throws', async () => {
      apiClient.fetchAttachmentsByPageTitle.mockRejectedValue(new Error('lookup boom'));

      const page = basePage(PAGE_BODY_OTHER_PAGE_IMAGE);
      const result = await inliner.inlineImages(page, []);

      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
    });
  });

  describe('malformed / edge-case bodies', () => {
    it('leaves a self-closing <ac:image/> macro untouched (no resource reference)', async () => {
      const page = basePage(PAGE_BODY_SELF_CLOSING_IMAGE);
      const result = await inliner.inlineImages(page, [sampleDiscoveredImageAttachment]);
      expect(result.page.body).toBe(page.body);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves an unclosed <ac:image> tag untouched and preserves trailing content', async () => {
      // Malformed body where <ac:image> is opened but never closed. The parser would
      // otherwise synthesize a close at EOF and we would splice from '<ac:image>' all
      // the way to the end of the body, destroying everything after it.
      const page = basePage(PAGE_BODY_UNCLOSED_IMAGE);
      const result = await inliner.inlineImages(page, [sampleDiscoveredImageAttachment]);
      expect(result.page.body).toBe(page.body);
      expect(result.page.body.endsWith('<p>more</p>')).toBe(true);
      expect(result.inlinedAttachmentIds.size).toBe(0);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('inlines the attachment while leaving an adjacent external <ri:url> macro untouched', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_MIXED_URL_AND_ATTACHMENT);

      const result = await inliner.inlineImages(page, [sampleDiscoveredImageAttachment]);

      expect(result.page.body).toContain(
        '<ac:image><ri:url ri:value="https://example.com/banner.png"/></ac:image>',
      );
      expect(result.page.body).toContain(
        `src="data:image/png;base64,${imageBuffer().toString('base64')}"`,
      );
      expect(result.inlinedAttachmentIds.size).toBe(1);
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledTimes(1);
    });

    it('inlines an <ac:image> nested several levels deep inside a table cell', async () => {
      // Confluence happily places image macros inside any block container. The parser
      // must find them at any depth, not just as direct children of the page body.
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_IMAGE_NESTED_IN_TABLE);

      const result = await inliner.inlineImages(page, [sampleDiscoveredImageAttachment]);

      expect(result.page.body).toContain(
        `src="data:image/png;base64,${imageBuffer().toString('base64')}"`,
      );
      expect(result.page.body).not.toContain('<ac:image');
      // Surrounding table structure must remain intact byte-for-byte.
      expect(result.page.body.startsWith('<table><tbody><tr><td><p>cell text</p>')).toBe(true);
      expect(result.page.body.endsWith('</td></tr></tbody></table>')).toBe(true);
      expect(result.inlinedAttachmentIds.size).toBe(1);
    });

    it('inlines two adjacent <ac:image> macros with no separator between them', async () => {
      apiClient.getAttachmentDownloadStream
        .mockResolvedValueOnce(Readable.from(Buffer.from('one')))
        .mockResolvedValueOnce(Readable.from(Buffer.from('two')));
      const body =
        '<ac:image><ri:attachment ri:filename="one.png"/></ac:image><ac:image><ri:attachment ri:filename="two.png"/></ac:image>';
      const att1: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        id: 'att-one',
        title: 'one.png',
      };
      const att2: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        id: 'att-two',
        title: 'two.png',
      };

      const result = await inliner.inlineImages(basePage(body), [att1, att2]);

      expect(result.page.body).not.toContain('<ac:image');
      expect(result.page.body).toContain(
        `src="data:image/png;base64,${Buffer.from('one').toString('base64')}"`,
      );
      expect(result.page.body).toContain(
        `src="data:image/png;base64,${Buffer.from('two').toString('base64')}"`,
      );
      // The two <img/> tags should be adjacent in the output too.
      expect(result.page.body).toMatch(/\/>\s*<img\s/);
    });

    it('inlines a body that is only a single <ac:image> macro', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const body = '<ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>';

      const result = await inliner.inlineImages(basePage(body), [sampleDiscoveredImageAttachment]);

      expect(result.page.body.startsWith('<img ')).toBe(true);
      expect(result.page.body.endsWith('/>')).toBe(true);
      expect(result.page.body).not.toContain('<ac:image');
    });
  });

  describe('partial-success and keying', () => {
    it('inlines the images it can and leaves the rest of the macros untouched', async () => {
      // Two image references on one page: the second filename has no matching attachment,
      // so only the first should be inlined.
      const body =
        '<p>a</p><ac:image><ri:attachment ri:filename="known.png"/></ac:image><p>b</p><ac:image><ri:attachment ri:filename="unknown.png"/></ac:image><p>c</p>';
      const knownAtt: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        id: 'att-known',
        title: 'known.png',
      };
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));

      const result = await inliner.inlineImages(basePage(body), [knownAtt]);

      expect(result.page.body).toContain('data:image/png;base64,');
      expect(result.page.body).toContain(
        '<ac:image><ri:attachment ri:filename="unknown.png"/></ac:image>',
      );
      expect(result.inlinedAttachmentIds).toEqual(
        new Set([buildInlinedAttachmentKey('1', 'att-known')]),
      );
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledTimes(1);
    });

    it('records the same attachment id under different keys when it appears on two different pages', async () => {
      // Other-page image lookup: lookup.pageId='99', resolved attachment id reused
      // elsewhere by coincidence. The inlined key must be pageId-scoped.
      apiClient.fetchAttachmentsByPageTitle.mockResolvedValue({
        pageId: '99',
        attachments: [createConfluenceImageAttachment({ id: 'shared-id', title: 'other.png' })],
      });
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));

      // Same inliner instance, two pages. First page (id='1') has a local image with the
      // same attachment id; the second page (id='2') has a reference to another page resolving
      // to the same id on a different page.
      const localAtt: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        id: 'shared-id',
        title: 'local.png',
        pageId: '1',
      };
      const localBody = '<ac:image><ri:attachment ri:filename="local.png"/></ac:image>';
      const local = await inliner.inlineImages(basePage(localBody), [localAtt]);
      const remote = await inliner.inlineImages(
        { ...basePage(PAGE_BODY_OTHER_PAGE_IMAGE), id: '2' },
        [],
      );

      expect(local.inlinedAttachmentIds).toEqual(
        new Set([buildInlinedAttachmentKey('1', 'shared-id')]),
      );
      expect(remote.inlinedAttachmentIds).toEqual(
        new Set([buildInlinedAttachmentKey('99', 'shared-id')]),
      );
      // Verify the keys are not equal — same attachment id, different pages.
      expect(buildInlinedAttachmentKey('1', 'shared-id')).not.toBe(
        buildInlinedAttachmentKey('99', 'shared-id'),
      );
    });
  });

  describe('mediaType + stream handling', () => {
    it('treats mediaType with charset/parameters as image and emits a clean data URI mime', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const att: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        mediaType: 'image/PNG; charset=binary',
      };

      const result = await inliner.inlineImages(basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE), [
        att,
      ]);

      expect(result.page.body).toContain('data:image/png;base64,');
      expect(result.page.body).not.toContain('charset=binary');
    });

    it('accumulates image bytes from a stream that yields strings (not Buffers)', async () => {
      const stringStream = Readable.from(['PNG', 'DATA']);
      apiClient.getAttachmentDownloadStream.mockResolvedValue(stringStream);

      const result = await inliner.inlineImages(basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE), [
        sampleDiscoveredImageAttachment,
      ]);

      expect(result.page.body).toContain(
        `src="data:image/png;base64,${Buffer.from('PNGDATA').toString('base64')}"`,
      );
    });
  });

  describe('attribute escaping', () => {
    it('html-escapes & < " in the alt attribute when the filename contains them', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      // Confluence storage format entity-encodes attribute values. The parser decodes
      // them back to the raw characters; the inliner must re-encode for the produced
      // <img alt="...">.
      const trickyName = 'a&b "c" <d>.png';
      const att: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        title: trickyName,
      };
      const body =
        '<ac:image><ri:attachment ri:filename="a&amp;b &quot;c&quot; &lt;d>.png"/></ac:image>';

      const result = await inliner.inlineImages(basePage(body), [att]);

      expect(result.page.body).toContain('alt="a&amp;b &quot;c&quot; &lt;d>.png"');
      // Must not contain a raw " inside the attribute value.
      expect(result.page.body).not.toMatch(/alt="[^"]*"c"/);
    });
  });
});
