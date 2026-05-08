import { aPage, aSpace } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';

/**
 * Confluence has one labeled page in one space; Unique starts empty.
 * Expected outcome: the space scope is created and one HTML file is ingested.
 */
export const singlePageScenario = defineScenario({
  confluence: {
    spaces: [aSpace()],
    pages: [
      aPage({
        id: 'p1',
        title: 'Page One',
        body: '<p>Hello, integration!</p>',
        labels: ['ai-ingest', 'engineering'],
      }),
    ],
  },
});
