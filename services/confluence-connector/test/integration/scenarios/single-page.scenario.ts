import { defineScenario } from '../scenario/scenario.builder';

/**
 * Confluence has one labeled page in one space; Unique starts empty.
 * Expected outcome: the space scope is created and one HTML file is ingested.
 */
export const singlePageScenario = defineScenario({
  confluence: {
    spaces: [{ id: 'space-1', key: 'SP', name: 'Space One' }],
    pages: [
      {
        id: 'p1',
        spaceKey: 'SP',
        title: 'Page One',
        body: '<p>Hello, integration!</p>',
        labels: ['ai-ingest', 'engineering'],
        versionWhen: '2026-05-01T10:00:00.000Z',
      },
    ],
  },
});
