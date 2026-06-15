import { page, space } from '../scenario/confluence-builders';
import { defineScenario } from '../scenario/scenario.builder';

/**
 * Confluence has three labeled pages in one space; Unique starts empty.
 *
 * Useful for failure-isolation tests where one page is mocked to fail and we
 * want to verify the other two still ingest successfully.
 */
export const threePagesOneSpaceScenario = defineScenario({
  confluence: {
    spaces: [space()],
    pages: [
      page({ id: 'p1', title: 'Page One' }),
      page({ id: 'p2', title: 'Page Two' }),
      page({ id: 'p3', title: 'Page Three' }),
    ],
  },
});
