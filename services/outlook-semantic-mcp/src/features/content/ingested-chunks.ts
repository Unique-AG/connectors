import { loadFeaturesConfig, McpBackendType } from '~/config';

// Only semantic search, in Unique mode, returns the ingested content ids `open_email` reads the
// matched chunks for. Other modes neither offer those parameters nor mention them.
export const OFFERS_INGESTED_CHUNKS =
  loadFeaturesConfig().mode === McpBackendType.MicrosoftGraphAndUniqueApi;
