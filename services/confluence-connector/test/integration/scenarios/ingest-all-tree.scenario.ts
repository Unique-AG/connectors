import { aPage, aSpace } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';

/**
 * Confluence has one labeled-with-`ai-ingest-all` root page that has two child
 * descendants; Unique starts empty. Expected outcome: all 3 pages are ingested
 * into the same space scope.
 */
export const ingestAllTreeScenario = defineScenario({
  confluence: {
    spaces: [aSpace()],
    pages: [
      aPage({ id: 'root', title: 'Root', body: '<p>Root</p>', labels: ['ai-ingest-all'] }),
      aPage({ id: 'child-a', parentId: 'root', title: 'Child A', body: '<p>A</p>', labels: [] }),
      aPage({ id: 'child-b', parentId: 'root', title: 'Child B', body: '<p>B</p>', labels: [] }),
    ],
  },
});
