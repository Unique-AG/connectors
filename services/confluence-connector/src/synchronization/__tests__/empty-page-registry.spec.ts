import { Smeared } from '@unique-ag/utils';
import { describe, expect, it } from 'vitest';
import { ContentType } from '../../confluence-api';
import { EmptyPageRegistry } from '../empty-page-registry';
import type { DiscoveredPage } from '../sync.types';

const FIRST_VERSION = '2026-02-01T00:00:00.000Z';
const EDITED_VERSION = '2026-03-01T00:00:00.000Z';

function makeDiscoveredPage(id: string, versionTimestamp = FIRST_VERSION): DiscoveredPage {
  return {
    id,
    title: new Smeared(`Page ${id}`, false),
    type: ContentType.PAGE,
    spaceId: 'space-1',
    spaceKey: 'SP',
    spaceName: 'Space',
    versionTimestamp,
    webUrl: `https://confluence.example.com/wiki/${id}`,
    labels: ['ai-ingest'],
  };
}

describe('EmptyPageRegistry', () => {
  it('knows a page as empty at the version it was marked at', () => {
    const registry = new EmptyPageRegistry();
    registry.markEmpty(makeDiscoveredPage('blank'));

    expect(registry.isKnownEmpty(makeDiscoveredPage('blank'))).toBe(true);
  });

  it('does not know a page as empty once it has a new version', () => {
    const registry = new EmptyPageRegistry();
    registry.markEmpty(makeDiscoveredPage('blank'));

    expect(registry.isKnownEmpty(makeDiscoveredPage('blank', EDITED_VERSION))).toBe(false);
  });

  it('does not know a page that was never marked', () => {
    const registry = new EmptyPageRegistry();

    expect(registry.isKnownEmpty(makeDiscoveredPage('unknown'))).toBe(false);
  });

  it('forgets a page', () => {
    const registry = new EmptyPageRegistry();
    registry.markEmpty(makeDiscoveredPage('blank'));

    registry.forget('blank');

    expect(registry.isKnownEmpty(makeDiscoveredPage('blank'))).toBe(false);
  });

  it('keeps only the pages that discovery still returns', () => {
    const registry = new EmptyPageRegistry();
    const kept = makeDiscoveredPage('kept');
    const removed = makeDiscoveredPage('removed');
    registry.markEmpty(kept);
    registry.markEmpty(removed);

    registry.retainOnly([kept, makeDiscoveredPage('never-empty')]);

    expect(registry.isKnownEmpty(kept)).toBe(true);
    expect(registry.isKnownEmpty(removed)).toBe(false);
  });
});
