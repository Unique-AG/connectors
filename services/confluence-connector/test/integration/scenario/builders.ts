import type {
  ScenarioAttachment,
  ScenarioPage,
  ScenarioSpace,
  ScenarioUniqueFile,
  ScenarioUniqueScope,
} from './scenario.types';

const DEFAULT_VERSION = '2026-05-01T10:00:00.000Z';
const DEFAULT_SPACE_KEY = 'SP';
const DEFAULT_INGEST_LABEL = 'ai-ingest';

/**
 * Entity builders that produce well-formed scenario primitives with sensible defaults.
 *
 * The override parameter lets tests focus on what matters:
 *
 *     aPage({ id: 'p1', body: '<p>Custom</p>' })
 *
 * instead of repeating spaceKey, labels, versionWhen, etc. on every page.
 */

export function aSpace(overrides: Partial<ScenarioSpace> = {}): ScenarioSpace {
  return {
    id: 'space-1',
    key: DEFAULT_SPACE_KEY,
    name: 'Space One',
    ...overrides,
  };
}

export function aPage(overrides: Partial<ScenarioPage> & Pick<ScenarioPage, 'id'>): ScenarioPage {
  return {
    spaceKey: DEFAULT_SPACE_KEY,
    title: `Page ${overrides.id}`,
    body: `<p>Body of ${overrides.id}</p>`,
    labels: [DEFAULT_INGEST_LABEL],
    versionWhen: DEFAULT_VERSION,
    ...overrides,
  };
}

export function anAttachment(
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

export function aUniqueFile(
  overrides: Partial<ScenarioUniqueFile> & Pick<ScenarioUniqueFile, 'id' | 'key'>,
): ScenarioUniqueFile {
  return {
    byteSize: 64,
    mimeType: 'text/html',
    updatedAt: DEFAULT_VERSION,
    ...overrides,
  };
}

export function aUniqueScope(
  overrides: Partial<ScenarioUniqueScope> & Pick<ScenarioUniqueScope, 'id' | 'name'>,
): ScenarioUniqueScope {
  return {
    parentId: null,
    externalId: null,
    ...overrides,
  };
}
