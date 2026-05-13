import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';

interface SubQueryLimits {
  min: number;
  max: number;
  default: number;
  description: string;
}

interface SearchConfig {
  // Max emails returned by search-emails.query.ts
  maxOutputEmails: number;
  msGraph: {
    // How many emails does the ms-graph-kql-search-emails.query.ts return
    maxEmailsLimit: number;
    // For every ms graph sub query what's the config for their min / max / default and description.
    subQueryLimits: SubQueryLimits;
  };
  semanticSearch: {
    // How many emails does the semantic-search-emails.query.ts return
    maxEmailsLimit: number;
    // For every semantic search sub query what's the config for their min / max / default and description.
    subQueryChunksLimits: SubQueryLimits;
  };
}

const getMsGraphDescription = (subQueryLimits: Omit<SubQueryLimits, 'description'>): string =>
  `Maximum number of results to return for this query. Must be between ${subQueryLimits.min} and ${subQueryLimits.max}. Default is ${subQueryLimits.default}. Use a lower value for targeted searches; the default is appropriate for broad or exploratory queries.`;

const msGraphOnlySubQueryLimits: Omit<SubQueryLimits, 'description'> = {
  max: 150,
  min: 10,
  default: 100,
};

const msGraphAndSemanticSearchSubQueryLimits: Omit<SubQueryLimits, 'description'> = {
  max: 100,
  min: 10,
  default: 100,
};

export const SEARCH_CONFIG: SearchConfig = isMicrosoftGraphBackend()
  ? {
      maxOutputEmails: 150,
      msGraph: {
        maxEmailsLimit: 150,
        subQueryLimits: {
          ...msGraphOnlySubQueryLimits,
          description: getMsGraphDescription(msGraphOnlySubQueryLimits),
        },
      },
      semanticSearch: {
        maxEmailsLimit: 0,
        subQueryChunksLimits: { min: 0, max: 0, default: 0, description: '' },
      },
    }
  : {
      maxOutputEmails: 200,
      msGraph: {
        maxEmailsLimit: 100,
        subQueryLimits: {
          ...msGraphAndSemanticSearchSubQueryLimits,
          description: getMsGraphDescription(msGraphAndSemanticSearchSubQueryLimits),
        },
      },
      semanticSearch: {
        maxEmailsLimit: 100,
        subQueryChunksLimits: {
          min: 100,
          max: 200,
          default: 100,
          description: [
            'Maximum number of results to return. Must be between 100 and 200.',
            'If the search query is targeted (e.g. looking for a specific email or thread), pass 100 (the minimum).',
            'If the query is fuzzy or broad (e.g. "overview of all emails from alice@example.com", "list emails from last week", "what happened last week"), pick a limit between 100 and 200.',
            'When the expected result set is large, always use 200.',
          ].join(' '),
        },
      },
    };
