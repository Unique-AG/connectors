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
import { PageImageInliner } from '../page-image-inliner';
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
  overrides: {
    maxFileSizeMb?: number;
    allowedMimeTypes?: string[];
    inlineImagesEnabled?: boolean;
  } = {},
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
        inlineImagesEnabled: overrides.inlineImagesEnabled ?? true,
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
      const result = await inliner.inlineImagesInPage(page, []);
      expect(result).toBe(page);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('returns the page unchanged when no <ac:image> macros are present', async () => {
      const page = basePage('<p>just text</p>');
      const result = await inliner.inlineImagesInPage(page, []);
      expect(result).toBe(page);
    });

    it('leaves every image for the standalone pass when inlining is disabled', async () => {
      // Escape hatch for platforms older than 2026.24.0: with inlining off, the page body is
      // returned untouched so the images flow through standalone ingestion.
      const disabledInliner = new PageImageInliner(
        createTestTenantConfig({ inlineImagesEnabled: false }),
        apiClient,
      );
      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);

      const result = await disabledInliner.inlineImagesInPage(page, [
        sampleDiscoveredImageAttachment,
      ]);

      expect(result).toBe(page);
      expect(result.body).toContain('<ac:image');
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });
  });

  describe('current-page attachment inlining', () => {
    it('replaces a single <ac:image> with <img src="data:...;base64,...">', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);

      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);

      const expectedBase64 = imageBuffer().toString('base64');
      expect(result.body).toContain(`src="data:image/png;base64,${expectedBase64}"`);
      expect(result.body).not.toContain('<ac:image');
      expect(result.body.startsWith('<p>before</p>')).toBe(true);
      expect(result.body.endsWith('<p>after</p>')).toBe(true);
    });

    it('preserves byte-perfect surroundings of the swapped block', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_WITH_CDATA_AND_IMAGE);

      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);

      expect(result.body).toContain(
        '<ac:plain-text-body><![CDATA[const x = "<not a tag>" & 1 < 2;]]></ac:plain-text-body>',
      );
      expect(result.body).not.toContain('<ac:image');
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

      const result = await inliner.inlineImagesInPage(
        basePage(PAGE_BODY_MULTIPLE_CURRENT_PAGE_IMAGES),
        [oneAtt, twoAtt],
      );

      expect(result.body).toContain(
        `src="data:image/png;base64,${Buffer.from('one').toString('base64')}"`,
      );
      expect(result.body).toContain(
        `src="data:image/jpeg;base64,${Buffer.from('two').toString('base64')}"`,
      );
      expect(result.body).not.toContain('<ac:image');
    });

    it('maps ac:alt, ac:title, ac:width, ac:height onto the produced <img>', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const result = await inliner.inlineImagesInPage(basePage(PAGE_BODY_IMAGE_WITH_ATTRS), [
        sampleDiscoveredImageAttachment,
      ]);

      expect(result.body).toMatch(/<img\s[^>]*\balt="An alt"/);
      expect(result.body).toMatch(/<img\s[^>]*\btitle="A title"/);
      expect(result.body).toMatch(/<img\s[^>]*\bwidth="320"/);
      expect(result.body).toMatch(/<img\s[^>]*\bheight="240"/);
      expect(result.body).not.toMatch(/ac:align="center"/);
      expect(result.body).not.toMatch(/\balign="center"/);
      expect(result.body).not.toMatch(/\bthumbnail=/);
    });
  });

  describe('skip / fallback cases', () => {
    it('leaves <ac:image> untouched when the filename is not among page attachments', async () => {
      const page = basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE);
      const result = await inliner.inlineImagesInPage(page, []);
      expect(result.body).toBe(page.body);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves <ac:image> untouched when the matching attachment is not image/*', async () => {
      const page = basePage('<ac:image><ri:attachment ri:filename="spec.pdf"/></ac:image>');
      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredPdfAttachment]);
      expect(result.body).toBe(page.body);
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
      const result = await smallLimitInliner.inlineImagesInPage(page, [oversize]);
      expect(result.body).toBe(page.body);
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
      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);

      expect(result.body).toBe(page.body);
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
      const result = await inliner.inlineImagesInPage(page, [gifAttachment]);
      expect(result.body).toBe(page.body);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves <ri:url> external images untouched and never fetches them', async () => {
      const page = basePage(PAGE_BODY_EXTERNAL_URL_IMAGE);
      const result = await inliner.inlineImagesInPage(page, []);
      expect(result.body).toBe(page.body);
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
      const result = await inliner.inlineImagesInPage(page, []);

      expect(apiClient.fetchAttachmentsByPageTitle).toHaveBeenCalledWith('OTHER', 'Other Page');
      expect(apiClient.fetchAttachmentsByPageTitle).toHaveBeenCalledTimes(1);
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledWith(
        'remote-att-1',
        '77',
        '/download/attachments/77/other.png',
      );
      expect(result.body).toContain(
        `src="data:image/png;base64,${imageBuffer().toString('base64')}"`,
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

      const result = await inliner.inlineImagesInPage(
        basePage(PAGE_BODY_TWO_REFERENCES_SAME_OTHER_PAGE),
        [],
      );

      // No lookup cache: each reference fetches the referenced page's attachments independently.
      expect(apiClient.fetchAttachmentsByPageTitle).toHaveBeenCalledTimes(2);
      expect(result.body).not.toContain('<ac:image');
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
      const result = await inliner.inlineImagesInPage(page, []);

      expect(result.body).toBe(page.body);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('leaves an other-page macro untouched when the referenced page is not found', async () => {
      apiClient.fetchAttachmentsByPageTitle.mockResolvedValue(null);

      const page = basePage(PAGE_BODY_OTHER_PAGE_IMAGE);
      const result = await inliner.inlineImagesInPage(page, []);

      expect(result.body).toBe(page.body);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('resolves a same-space <ri:page> reference (no ri:space-key) using the current page space', async () => {
      // Confluence omits ri:space-key when the referenced page is in the same space. The lookup
      // must then default to the current page's space (basePage uses 'SP') rather than be skipped.
      apiClient.fetchAttachmentsByPageTitle.mockResolvedValue({
        pageId: '77',
        attachments: [
          createConfluenceImageAttachment({ id: 'same-space-att', title: 'other.png' }),
        ],
      });
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));

      const body =
        '<ac:image><ri:attachment ri:filename="other.png"><ri:page ri:content-title="Other Page"/></ri:attachment></ac:image>';
      const result = await inliner.inlineImagesInPage(basePage(body), []);

      expect(apiClient.fetchAttachmentsByPageTitle).toHaveBeenCalledWith('SP', 'Other Page');
      expect(result.body).toContain(
        `src="data:image/png;base64,${imageBuffer().toString('base64')}"`,
      );
    });

    it('does not fill an <ri:page> macro lacking ri:content-title with a same-named current-page attachment', async () => {
      // Without ri:content-title the source page can't be identified. The presence of <ri:page>
      // signals intent to reference another page, so the macro must NOT silently fall back to a
      // same-named attachment on the current page. (That attachment is still appended at the end
      // like any other unreferenced image, but it never replaces the macro.)
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const samePageDecoy: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        title: 'other.png',
      };
      const body =
        '<ac:image><ri:attachment ri:filename="other.png"><ri:page ri:space-key="OTHER"/></ri:attachment></ac:image>';

      const result = await inliner.inlineImagesInPage(basePage(body), [samePageDecoy]);

      // the macro is left untouched (not replaced by the decoy)...
      expect(result.body.startsWith(body)).toBe(true);
      expect(apiClient.fetchAttachmentsByPageTitle).not.toHaveBeenCalled();
      // ...the decoy is instead appended at the end, like any unreferenced page image.
      expect(result.body.endsWith('alt="other.png" /></p>')).toBe(true);
      expect(mockLogger.warn).toHaveBeenCalledWith(
        expect.objectContaining({
          pageId: '1',
          msg: 'Image macro references an unresolvable attachment, leaving macro untouched',
        }),
      );
    });

    it('leaves an other-page macro untouched when fetchAttachmentsByPageTitle throws', async () => {
      apiClient.fetchAttachmentsByPageTitle.mockRejectedValue(new Error('lookup boom'));

      const page = basePage(PAGE_BODY_OTHER_PAGE_IMAGE);
      const result = await inliner.inlineImagesInPage(page, []);

      expect(result.body).toBe(page.body);
    });
  });

  describe('malformed / edge-case bodies', () => {
    it('leaves a self-closing <ac:image/> macro in place and appends the unreferenced attachment', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_SELF_CLOSING_IMAGE);
      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);
      // The self-closing macro carries no resource reference, so it is left untouched...
      expect(result.body.startsWith('<p>before</p><ac:image/><p>after</p>')).toBe(true);
      // ...and the attachment, referenced by no macro, is appended at the end of the body.
      expect(
        result.body.endsWith(
          `<p><img src="data:image/png;base64,${imageBuffer().toString('base64')}" alt="diagram.png" /></p>`,
        ),
      ).toBe(true);
    });

    it('leaves an unclosed <ac:image> tag untouched and preserves trailing content', async () => {
      // Malformed body where <ac:image> is opened but never closed, referencing a filename
      // that DOES resolve to a discovered attachment. The parser would otherwise synthesize a
      // close at EOF and we would splice from '<ac:image>' all the way to the end of the body,
      // destroying everything after it. The close-tag guard must drop the macro entirely, so the
      // original body (including the trailing <p>more</p>) survives byte-for-byte as a prefix.
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_UNCLOSED_IMAGE);
      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);
      expect(result.body.startsWith(page.body)).toBe(true);
      expect(result.body).toContain('<ri:attachment ri:filename="diagram.png"/><p>more</p>');
      // The macro never consumed the attachment, so it is appended at the end instead.
      expect(
        result.body.endsWith(
          `<p><img src="data:image/png;base64,${imageBuffer().toString('base64')}" alt="diagram.png" /></p>`,
        ),
      ).toBe(true);
    });

    it('inlines the attachment while leaving an adjacent external <ri:url> macro untouched', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_MIXED_URL_AND_ATTACHMENT);

      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);

      expect(result.body).toContain(
        '<ac:image><ri:url ri:value="https://example.com/banner.png"/></ac:image>',
      );
      expect(result.body).toContain(
        `src="data:image/png;base64,${imageBuffer().toString('base64')}"`,
      );
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledTimes(1);
    });

    it('inlines an <ac:image> nested several levels deep inside a table cell', async () => {
      // Confluence happily places image macros inside any block container. The parser
      // must find them at any depth, not just as direct children of the page body.
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage(PAGE_BODY_IMAGE_NESTED_IN_TABLE);

      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);

      expect(result.body).toContain(
        `src="data:image/png;base64,${imageBuffer().toString('base64')}"`,
      );
      expect(result.body).not.toContain('<ac:image');
      // Surrounding table structure must remain intact byte-for-byte.
      expect(result.body.startsWith('<table><tbody><tr><td><p>cell text</p>')).toBe(true);
      expect(result.body.endsWith('</td></tr></tbody></table>')).toBe(true);
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

      const result = await inliner.inlineImagesInPage(basePage(body), [att1, att2]);

      expect(result.body).not.toContain('<ac:image');
      expect(result.body).toContain(
        `src="data:image/png;base64,${Buffer.from('one').toString('base64')}"`,
      );
      expect(result.body).toContain(
        `src="data:image/png;base64,${Buffer.from('two').toString('base64')}"`,
      );
      // The two <img/> tags should be adjacent in the output too.
      expect(result.body).toMatch(/\/>\s*<img\s/);
    });

    it('inlines a body that is only a single <ac:image> macro', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const body = '<ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>';

      const result = await inliner.inlineImagesInPage(basePage(body), [
        sampleDiscoveredImageAttachment,
      ]);

      expect(result.body.startsWith('<img ')).toBe(true);
      expect(result.body.endsWith('/>')).toBe(true);
      expect(result.body).not.toContain('<ac:image');
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

      const result = await inliner.inlineImagesInPage(basePage(body), [knownAtt]);

      expect(result.body).toContain('data:image/png;base64,');
      expect(result.body).toContain(
        '<ac:image><ri:attachment ri:filename="unknown.png"/></ac:image>',
      );
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledTimes(1);
    });
  });

  describe('mediaType + stream handling', () => {
    it('treats mediaType with charset/parameters as image and emits a clean data URI mime', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const att: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        mediaType: 'image/PNG; charset=binary',
      };

      const result = await inliner.inlineImagesInPage(
        basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE),
        [att],
      );

      expect(result.body).toContain('data:image/png;base64,');
      expect(result.body).not.toContain('charset=binary');
    });

    it('accumulates image bytes from a stream that yields strings (not Buffers)', async () => {
      const stringStream = Readable.from(['PNG', 'DATA']);
      apiClient.getAttachmentDownloadStream.mockResolvedValue(stringStream);

      const result = await inliner.inlineImagesInPage(
        basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE),
        [sampleDiscoveredImageAttachment],
      );

      expect(result.body).toContain(
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

      const result = await inliner.inlineImagesInPage(basePage(body), [att]);

      expect(result.body).toContain('alt="a&amp;b &quot;c&quot; &lt;d>.png"');
      // Must not contain a raw " inside the attribute value.
      expect(result.body).not.toMatch(/alt="[^"]*"c"/);
    });
  });

  describe('appending unreferenced attachments', () => {
    it('appends an image attachment that no macro references to the end of the body', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));
      const page = basePage('<p>just text</p>');

      const result = await inliner.inlineImagesInPage(page, [sampleDiscoveredImageAttachment]);

      const expectedBase64 = imageBuffer().toString('base64');
      expect(result.body.startsWith('<p>just text</p>')).toBe(true);
      expect(
        result.body.endsWith(
          `<p><img src="data:image/png;base64,${expectedBase64}" alt="diagram.png" /></p>`,
        ),
      ).toBe(true);
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledTimes(1);
    });

    it('inlines a referenced image in place and appends an unreferenced one after it', async () => {
      apiClient.getAttachmentDownloadStream
        .mockResolvedValueOnce(Readable.from(Buffer.from('PNG')))
        .mockResolvedValueOnce(Readable.from(Buffer.from('JPG')));
      const chart: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        id: 'att-chart',
        title: 'chart.jpg',
        mediaType: 'image/jpeg',
        downloadPath: '/download/attachments/1/chart.jpg',
      };

      // body references diagram.png via a macro; chart.jpg is attached but not referenced.
      const result = await inliner.inlineImagesInPage(
        basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE),
        [sampleDiscoveredImageAttachment, chart],
      );

      expect(result.body).not.toContain('<ac:image');
      expect(result.body).toContain(
        `src="data:image/png;base64,${Buffer.from('PNG').toString('base64')}"`,
      );
      expect(
        result.body.endsWith(
          `<p><img src="data:image/jpeg;base64,${Buffer.from('JPG').toString('base64')}" alt="chart.jpg" /></p>`,
        ),
      ).toBe(true);
      // the macro-inlined image comes before the appended one.
      expect(result.body.indexOf('alt="diagram"')).toBeLessThan(
        result.body.indexOf('alt="chart.jpg"'),
      );
    });

    it('does not append an image that a macro already references (no duplicate)', async () => {
      apiClient.getAttachmentDownloadStream.mockResolvedValue(Readable.from(imageBuffer()));

      const result = await inliner.inlineImagesInPage(
        basePage(PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE),
        [sampleDiscoveredImageAttachment],
      );

      expect((result.body.match(/<img /g) ?? []).length).toBe(1);
      expect(apiClient.getAttachmentDownloadStream).toHaveBeenCalledTimes(1);
    });

    it('does not append an unreferenced attachment that exceeds maxFileSizeMb', async () => {
      const oversize: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        fileSize: 5 * 1024 * 1024,
      };
      const smallLimitInliner = new PageImageInliner(
        createTestTenantConfig({ maxFileSizeMb: 1 }),
        apiClient,
      );
      const page = basePage('<p>just text</p>');

      const result = await smallLimitInliner.inlineImagesInPage(page, [oversize]);

      expect(result).toBe(page);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });

    it('does not append an unreferenced attachment whose image type is not in allowedMimeTypes', async () => {
      const gifAttachment: DiscoveredAttachment = {
        ...sampleDiscoveredImageAttachment,
        mediaType: 'image/gif',
      };
      const page = basePage('<p>just text</p>');

      const result = await inliner.inlineImagesInPage(page, [gifAttachment]);

      expect(result).toBe(page);
      expect(apiClient.getAttachmentDownloadStream).not.toHaveBeenCalled();
    });
  });
});
