/**
 * Behavior: single-page sync (`ai-ingest` label).
 *
 * The connector ingests only those pages explicitly labeled with `ai-ingest`,
 * along with their attachments. Sibling pages and descendants in the same space
 * are ignored unless they too carry the label (or `ai-ingest-all`, which is
 * exercised in `subtree-sync.integration-spec.ts`).
 */
import { createHash } from 'node:crypto';
import { afterEach, describe, expect, it } from 'vitest';
import { page, space } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';
import { buildScenarioContext, type ScenarioContext } from '../scenario-context/scenario-context';
import { getUniqueState } from '../scenario-context/unique-state';
import {
  pageWithAttachmentBytes,
  pageWithAttachmentScenario,
} from '../scenarios/page-with-attachment.scenario';

describe('single-page sync', () => {
  let ctx: ScenarioContext | undefined;

  afterEach(async () => {
    await ctx?.close();
    ctx = undefined;
  });

  // The canonical single-page flow: a single labeled page becomes one HTML file
  // in Unique, under a scope mirroring the Confluence space.
  it('ingests a single labeled page', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({
            id: 'p1',
            title: 'Page One',
            body: '<p>Hello, integration!</p>',
            labels: ['ai-ingest', 'engineering'],
          }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

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
      metadata: expect.objectContaining({ spaceKey: 'SP', spaceName: 'Space One' }),
    });
  });

  // Attachments on a labeled page are ingested alongside the page itself, each
  // as its own file in Unique with key `<page-id>::<attachment-id>`.
  it('ingests a labeled page together with its attachments', async () => {
    ctx = buildScenarioContext(pageWithAttachmentScenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    const filesByKey = new Map(state.files.map((file) => [file.key, file]));

    expect(filesByKey.size).toBe(2);

    expect(filesByKey.get('tenant1/space-1_SP/p1')).toMatchObject({
      mimeType: 'text/html',
      bodyText: '<p>See attached.</p>',
    });

    expect(filesByKey.get('tenant1/space-1_SP/p1::att-1')).toMatchObject({
      mimeType: 'application/pdf',
      byteSize: pageWithAttachmentBytes.byteLength,
      bodySize: pageWithAttachmentBytes.byteLength,
      bodyHash: sha256(pageWithAttachmentBytes),
    });
  });

  // Selectivity: only labeled pages are ingested even when unlabeled pages
  // share the same space. Tests that the scanner's CQL filter is honored.
  it('does not ingest unlabeled pages in the same space', async () => {
    const scenario = defineScenario({
      confluence: {
        spaces: [space()],
        pages: [
          page({ id: 'labeled', title: 'Will be ingested', labels: ['ai-ingest'] }),
          page({ id: 'unlabeled-a', title: 'Will be ignored', labels: [] }),
          page({ id: 'unlabeled-b', title: 'Will also be ignored', labels: ['draft'] }),
        ],
      },
    });
    ctx = buildScenarioContext(scenario);

    const result = await ctx.runSync();

    expect(result).toEqual({ status: 'success' });

    const state = getUniqueState(ctx.unique);
    expect(state.files.map((file) => file.key)).toEqual(['tenant1/space-1_SP/labeled']);
  });
});

function sha256(buf: Buffer): string {
  return createHash('sha256').update(buf).digest('hex');
}
