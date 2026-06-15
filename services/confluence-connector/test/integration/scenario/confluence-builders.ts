import {
  DEFAULT_INGEST_LABEL,
  DEFAULT_SPACE_ID,
  DEFAULT_SPACE_KEY,
  DEFAULT_VERSION,
} from './defaults';
import type { ScenarioAttachment, ScenarioPage, ScenarioSpace } from './scenario.types';

/**
 * Builders for Confluence-side scenario primitives (the source content a sync
 * reads from). They produce well-formed entities with sensible defaults so the
 * override parameter lets tests focus on what matters:
 *
 *     page({ id: 'p1', body: '<p>Custom</p>' })
 *
 * instead of repeating spaceKey, labels, versionWhen, etc. on every page.
 */

export function space(overrides: Partial<ScenarioSpace> = {}): ScenarioSpace {
  return {
    id: DEFAULT_SPACE_ID,
    key: DEFAULT_SPACE_KEY,
    name: 'Space One',
    ...overrides,
  };
}

export function page(overrides: Partial<ScenarioPage> & Pick<ScenarioPage, 'id'>): ScenarioPage {
  return {
    spaceKey: DEFAULT_SPACE_KEY,
    title: `Page ${overrides.id}`,
    body: `<p>Body of ${overrides.id}</p>`,
    labels: [DEFAULT_INGEST_LABEL],
    versionWhen: DEFAULT_VERSION,
    ...overrides,
  };
}

export function attachment(
  overrides: Partial<ScenarioAttachment> & Pick<ScenarioAttachment, 'id'>,
): ScenarioAttachment {
  return {
    title: `${overrides.id}.pdf`,
    mediaType: 'application/pdf',
    bytes: Buffer.from(`%PDF-1.4\n% fake bytes for ${overrides.id}\n%%EOF\n`),
    versionWhen: DEFAULT_VERSION,
    ...overrides,
  };
}
