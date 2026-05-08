import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it } from 'vitest';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';
import { ingestAllTreeScenario } from '../scenarios/ingest-all-tree.scenario';
import {
  pageWithAttachmentBytes,
  pageWithAttachmentScenario,
} from '../scenarios/page-with-attachment.scenario';
import { singlePageScenario } from '../scenarios/single-page.scenario';

describe('sync — Confluence has content, Unique is empty', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  it('ingests a single labeled page into a fresh Unique', async () => {
    ctx = buildScenarioContext(singlePageScenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    expect(state.scopes).toEqual([
      expect.objectContaining({ path: '/Confluence', externalId: 'confc:cloud:cloud-1' }),
      expect.objectContaining({
        path: '/Confluence/SP',
        externalId: 'confc:tenant1:space-1:SP',
      }),
    ]);

    expect(state.files).toHaveLength(1);
    expect(state.files[0]).toMatchObject({
      key: 'tenant1/space-1_SP/p1',
      mimeType: 'text/html',
      bodyText: '<p>Hello, integration!</p>',
      metadata: expect.objectContaining({
        spaceKey: 'SP',
        spaceName: 'Space One',
      }),
    });
  });

  it('ingests a page with one PDF attachment into a fresh Unique', async () => {
    ctx = buildScenarioContext(pageWithAttachmentScenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const filesByKey = new Map(state.files.map((file) => [file.key, file]));

    expect(filesByKey.size).toBe(2);

    const pageFile = filesByKey.get('tenant1/space-1_SP/p1');
    expect(pageFile).toMatchObject({
      mimeType: 'text/html',
      bodyText: '<p>See attached.</p>',
    });

    const attachmentFile = filesByKey.get('tenant1/space-1_SP/p1::att-1');
    expect(attachmentFile).toMatchObject({
      mimeType: 'application/pdf',
      bodySize: pageWithAttachmentBytes.byteLength,
      byteSize: pageWithAttachmentBytes.byteLength,
      bodyHash: sha256(pageWithAttachmentBytes),
    });
  });

  it('ingests a page labeled ai-ingest-all together with all its descendants', async () => {
    ctx = buildScenarioContext(ingestAllTreeScenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);

    expect(state.scopes.map((scope) => scope.path)).toEqual(['/Confluence', '/Confluence/SP']);

    const fileKeys = state.files.map((file) => file.key).sort();
    expect(fileKeys).toEqual([
      'tenant1/space-1_SP/child-a',
      'tenant1/space-1_SP/child-b',
      'tenant1/space-1_SP/root',
    ]);

    for (const file of state.files) {
      expect(file.mimeType).toBe('text/html');
      expect(file.bodyText).toMatch(/^<p>/);
    }
  });
});

function sha256(buf: Buffer): string {
  return createHash('sha256').update(buf).digest('hex');
}
