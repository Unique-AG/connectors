/**
 * Behavior: attachment ingestion controls (#494).
 *
 * The connector ingests file attachments alongside their parent page, subject
 * to three configuration knobs:
 *
 *  - `attachments.allowedMimeTypes` — only these MIME types are ingested.
 *  - `attachments.maxFileSizeMb` — anything larger is filtered out at scan time.
 *  - `attachments.imageOcrEnabled` — when on, image attachments (`image/png`,
 *    `image/jpeg`) are registered with `ingestionConfig: { jpgReadMode:
 *    'DOC_INTELLIGENCE_DEFAULT' }` so Unique routes them through document
 *    intelligence OCR. Other types are unaffected.
 *
 * `attachments.mode = disabled` skips the entire attachment scan.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { attachment, page, space } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';

const ONE_MB = 1024 * 1024;

describe('attachments', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // Image attachments (PNG, JPEG) are first-class — both are ingested with
  // their original media type alongside the HTML page.
  it('ingests image attachments alongside the page', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            attachments: [
              attachment({
                id: 'att-png',
                title: 'diagram.png',
                mediaType: 'image/png',
                bytes: Buffer.from('PNG bytes'),
              }),
              attachment({
                id: 'att-jpg',
                title: 'photo.jpg',
                mediaType: 'image/jpeg',
                bytes: Buffer.from('JPEG bytes'),
              }),
            ],
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const filesByKey = new Map(state.files.map((file) => [file.key, file]));

    expect(filesByKey.get('tenant1/space-1_SP/p1::att-png')).toMatchObject({
      mimeType: 'image/png',
    });
    expect(filesByKey.get('tenant1/space-1_SP/p1::att-jpg')).toMatchObject({
      mimeType: 'image/jpeg',
    });
  });

  // The allowlist is consulted at scan time. Anything outside it is filtered
  // before reaching Unique's ingestion API.
  it('excludes attachments whose MIME type is not in the allowlist', async () => {
    const scenario = defineScenario({
      tenant: { allowedMimeTypes: ['application/pdf'] },
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            attachments: [
              attachment({ id: 'att-pdf', title: 'doc.pdf', mediaType: 'application/pdf' }),
              attachment({
                id: 'att-png',
                title: 'image.png',
                mediaType: 'image/png',
                bytes: Buffer.from('PNG bytes'),
              }),
              attachment({
                id: 'att-svg',
                title: 'logo.svg',
                mediaType: 'image/svg+xml',
                bytes: Buffer.from('<svg/>'),
              }),
            ],
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/p1',
      'tenant1/space-1_SP/p1::att-pdf',
    ]);
  });

  // The size limit is consulted at scan time. Oversized attachments are
  // filtered before reaching Unique.
  it('excludes attachments larger than the configured maxFileSizeMb', async () => {
    const scenario = defineScenario({
      tenant: { maxFileSizeMb: 1 },
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            attachments: [
              attachment({
                id: 'att-small',
                title: 'small.pdf',
                mediaType: 'application/pdf',
                bytes: Buffer.from('small file'),
              }),
              attachment({
                id: 'att-huge',
                title: 'huge.pdf',
                mediaType: 'application/pdf',
                // 2 MB — strictly larger than the 1 MB cap.
                bytes: Buffer.alloc(2 * ONE_MB, 0x42),
              }),
            ],
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key).sort()).toEqual([
      'tenant1/space-1_SP/p1',
      'tenant1/space-1_SP/p1::att-small',
    ]);
  });

  // OCR is opt-in per tenant. When enabled, image attachments are registered
  // with `jpgReadMode: 'DOC_INTELLIGENCE_DEFAULT'` so Unique routes them
  // through document intelligence; non-image attachments must be unaffected.
  it('requests OCR ingestionConfig for image attachments when imageOcr is enabled', async () => {
    const scenario = defineScenario({
      tenant: { imageOcrEnabled: true },
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            attachments: [
              attachment({
                id: 'att-png',
                title: 'diagram.png',
                mediaType: 'image/png',
                bytes: Buffer.from('PNG bytes'),
              }),
              attachment({
                id: 'att-jpg',
                title: 'photo.jpg',
                mediaType: 'image/jpeg',
                bytes: Buffer.from('JPEG bytes'),
              }),
              attachment({
                id: 'att-pdf',
                title: 'doc.pdf',
                mediaType: 'application/pdf',
              }),
            ],
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const filesByKey = new Map(state.files.map((file) => [file.key, file]));

    expect(filesByKey.get('tenant1/space-1_SP/p1::att-png')?.ingestionConfig).toEqual({
      jpgReadMode: 'DOC_INTELLIGENCE_DEFAULT',
    });
    expect(filesByKey.get('tenant1/space-1_SP/p1::att-jpg')?.ingestionConfig).toEqual({
      jpgReadMode: 'DOC_INTELLIGENCE_DEFAULT',
    });
    expect(filesByKey.get('tenant1/space-1_SP/p1::att-pdf')?.ingestionConfig).toBeNull();
    expect(filesByKey.get('tenant1/space-1_SP/p1')?.ingestionConfig).toBeNull();
  });

  // Scale check: a page with many attachments must ingest every one of them.
  // This exercises the per-page attachment fan-out under default concurrency
  // and asserts that nothing is dropped silently along the way.
  it('ingests every attachment when a page has 50 of them', async () => {
    const ATTACHMENT_COUNT = 50;
    const attachments = Array.from({ length: ATTACHMENT_COUNT }, (_, i) =>
      attachment({
        id: `att-${String(i + 1).padStart(2, '0')}`,
        title: `doc-${i + 1}.pdf`,
        mediaType: 'application/pdf',
        bytes: Buffer.from(`PDF bytes #${i + 1}`),
      }),
    );

    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [page({ id: 'p1', attachments })],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    const attachmentKeys = state.files
      .map((file) => file.key)
      .filter((key) => key.includes('::'))
      .sort();
    expect(attachmentKeys).toHaveLength(ATTACHMENT_COUNT);
    expect(attachmentKeys[0]).toBe('tenant1/space-1_SP/p1::att-01');
    expect(attachmentKeys[ATTACHMENT_COUNT - 1]).toBe('tenant1/space-1_SP/p1::att-50');
  });

  // When attachments are disabled, the scanner skips them entirely — only the
  // HTML page reaches Unique.
  it('ingests pages but no attachments when attachments are disabled', async () => {
    const scenario = defineScenario({
      tenant: { attachmentsEnabled: false },
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            attachments: [attachment({ id: 'att-1', title: 'doc.pdf' })],
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-1_SP/p1']);
  });
});
