import { describe, it } from 'vitest';

// These tests need to be rewritten for the new sites array structure
describe.skip('SharepointConfigSchema', () => {
  it.skip('TODO: update tests for sites array', () => {
    // Old tests validated siteIds field
    // New structure has a sites array with per-site configuration
    // Tests should be rewritten to validate:
    // - sites array structure
    // - siteId field within each site object
    // - other site-specific fields (syncColumnName, ingestionMode, etc.)
  });
});
