import { Smeared } from '@unique-ag/utils';
import { ContentType } from '../../confluence-api';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import type {
  DiscoveredAttachment,
  DiscoveredPage,
  DiscoveryResult,
  FetchedPage,
} from '../sync.types';

export const CONFLUENCE_BASE_URL = 'https://confluence.example.com';

export const discoveredPagesFixture: DiscoveredPage[] = [
  {
    id: '1',
    title: new Smeared('Page 1', false),
    type: ContentType.PAGE,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    versionTimestamp: '2026-02-01T00:00:00.000Z',
    webUrl: `${CONFLUENCE_BASE_URL}/page/1`,
    labels: ['ai-ingest'],
  },
];

export const discoveryResultFixture: DiscoveryResult = {
  pages: discoveredPagesFixture,
  attachments: [],
};

export const fetchedPagesFixture: FetchedPage[] = [
  {
    id: '1',
    title: new Smeared('Page 1', false),
    body: '<p>content</p>',
    webUrl: `${CONFLUENCE_BASE_URL}/page/1`,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    metadata: { confluenceLabels: ['engineering'] },
  },
];

export const PAGE_BODY_SINGLE_CURRENT_PAGE_IMAGE =
  '<p>before</p><ac:image ac:alt="diagram"><ri:attachment ri:filename="diagram.png"/></ac:image><p>after</p>';

export const PAGE_BODY_MULTIPLE_CURRENT_PAGE_IMAGES =
  '<h1>Title</h1><ac:image><ri:attachment ri:filename="one.png"/></ac:image><p>middle</p><ac:image><ri:attachment ri:filename="two.jpg"/></ac:image>';

export const PAGE_BODY_IMAGE_WITH_ATTRS =
  '<ac:image ac:alt="An alt" ac:title="A title" ac:width="320" ac:height="240" ac:align="center" ac:thumbnail="true"><ri:attachment ri:filename="diagram.png"/></ac:image>';

export const PAGE_BODY_OTHER_PAGE_IMAGE =
  '<p>see other page</p><ac:image><ri:attachment ri:filename="other.png"><ri:page ri:space-key="OTHER" ri:content-title="Other Page"/></ri:attachment></ac:image>';

export const PAGE_BODY_TWO_REFERENCES_SAME_OTHER_PAGE =
  '<ac:image><ri:attachment ri:filename="a.png"><ri:page ri:space-key="OTHER" ri:content-title="Other Page"/></ri:attachment></ac:image><ac:image><ri:attachment ri:filename="b.png"><ri:page ri:space-key="OTHER" ri:content-title="Other Page"/></ri:attachment></ac:image>';

export const PAGE_BODY_EXTERNAL_URL_IMAGE =
  '<ac:image><ri:url ri:value="https://example.com/banner.png"/></ac:image>';

export const PAGE_BODY_WITH_CDATA_AND_IMAGE =
  '<ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[const x = "<not a tag>" & 1 < 2;]]></ac:plain-text-body></ac:structured-macro><ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>';

export const PAGE_BODY_SELF_CLOSING_IMAGE = '<p>before</p><ac:image/><p>after</p>';

// Malformed: <ac:image> is opened but never closed. The filename intentionally matches a
// discovered attachment, so without the parser's close-tag guard the macro would resolve,
// download, and splice from its start to EOF — deleting the trailing <p>more</p>. The inliner
// must leave the surrounding content intact and skip the macro.
export const PAGE_BODY_UNCLOSED_IMAGE =
  '<p>start</p><ac:image><ri:attachment ri:filename="diagram.png"/><p>more</p>';

export const PAGE_BODY_MIXED_URL_AND_ATTACHMENT =
  '<p>external first</p><ac:image><ri:url ri:value="https://example.com/banner.png"/></ac:image><p>then attachment</p><ac:image><ri:attachment ri:filename="diagram.png"/></ac:image>';

// <ac:image> wrapped inside a table cell. Exercises the parser's any-depth traversal:
// the macro is not a direct child of the body, but several levels down inside <table>.
export const PAGE_BODY_IMAGE_NESTED_IN_TABLE =
  '<table><tbody><tr><td><p>cell text</p><ac:image><ri:attachment ri:filename="diagram.png"/></ac:image></td></tr></tbody></table>';

export const sampleDiscoveredImageAttachment: DiscoveredAttachment = {
  id: 'att-image-1',
  title: 'diagram.png',
  mediaType: 'image/png',
  fileSize: 4096,
  downloadPath: '/download/attachments/1/diagram.png',
  versionTimestamp: '2026-03-01T00:00:00.000Z',
  pageId: '1',
  spaceId: 'space-1',
  spaceKey: 'SP',
  spaceName: 'Space',
  webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1/attachments/att-image-1`,
};

export const sampleDiscoveredPdfAttachment: DiscoveredAttachment = {
  id: 'att-pdf-1',
  title: 'spec.pdf',
  mediaType: 'application/pdf',
  fileSize: 8192,
  downloadPath: '/download/attachments/1/spec.pdf',
  versionTimestamp: '2026-03-01T00:00:00.000Z',
  pageId: '1',
  spaceId: 'space-1',
  spaceKey: 'SP',
  spaceName: 'Space',
  webUrl: `${CONFLUENCE_BASE_URL}/wiki/spaces/SP/pages/1/attachments/att-pdf-1`,
};

export function createMockTenant(
  name: string,
  overrides: Partial<TenantContext> = {},
): TenantContext {
  return {
    name,
    config: {
      confluence: { baseUrl: CONFLUENCE_BASE_URL },
      processing: { scanIntervalCron: '*/5 * * * *', concurrency: 2 },
      ingestion: {},
    },
    isScanning: false,
    ...overrides,
  } as unknown as TenantContext;
}
