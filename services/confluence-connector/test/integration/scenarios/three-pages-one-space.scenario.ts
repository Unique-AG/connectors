import { aPage, aSpace } from '../scenario/builders';
import { defineScenario } from '../scenario/scenario.builder';

/**
 * Confluence has three labeled pages in one space; Unique starts empty.
 *
 * Useful for failure-injection tests where one page fails and we want to
 * verify the other two still ingest successfully.
 */
export const threePagesOneSpaceScenario = defineScenario({
  confluence: {
    spaces: [aSpace()],
    pages: [
      aPage({ id: 'p1', title: 'Page One' }),
      aPage({ id: 'p2', title: 'Page Two' }),
      aPage({ id: 'p3', title: 'Page Three' }),
    ],
  },
});
