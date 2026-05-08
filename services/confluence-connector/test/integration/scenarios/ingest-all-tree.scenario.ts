import { defineScenario } from '../scenario/scenario.builder';

/**
 * Confluence has one labeled-with-`ai-ingest-all` root page that has two child
 * descendants; Unique starts empty. Expected outcome: all 3 pages are ingested
 * into the same space scope.
 */
export const ingestAllTreeScenario = defineScenario({
  confluence: {
    spaces: [{ id: 'space-1', key: 'SP', name: 'Space One' }],
    pages: [
      {
        id: 'root',
        spaceKey: 'SP',
        title: 'Root',
        body: '<p>Root</p>',
        labels: ['ai-ingest-all'],
        versionWhen: '2026-05-01T10:00:00.000Z',
      },
      {
        id: 'child-a',
        spaceKey: 'SP',
        parentId: 'root',
        title: 'Child A',
        body: '<p>A</p>',
        labels: [],
        versionWhen: '2026-05-01T10:00:00.000Z',
      },
      {
        id: 'child-b',
        spaceKey: 'SP',
        parentId: 'root',
        title: 'Child B',
        body: '<p>B</p>',
        labels: [],
        versionWhen: '2026-05-01T10:00:00.000Z',
      },
    ],
  },
});
