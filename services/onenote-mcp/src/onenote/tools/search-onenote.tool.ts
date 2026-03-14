import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import type { UniqueConfigNamespaced } from '~/config';
import { GlobalThrottleMiddleware } from '~/msgraph/global-throttle.middleware';
import {
  type MetadataFilter,
  type PublicSearchRequest,
  SearchType,
  UniqueQLOperator,
} from '~/unique/unique.dtos';
import { UniqueContentService } from '~/unique/unique-content.service';
import { UniqueScopeService } from '~/unique/unique-scope.service';
import { extractSafeGraphError } from '~/utils/graph-error.filter';
import { OneNoteDeltaService } from '../onenote-delta.service';
import { OneNoteSyncService } from '../onenote-sync.service';

const SearchInputSchema = z.object({
  query: z.string().describe('Search query to find relevant content in OneNote pages'),
  notebookName: z.string().optional().describe('Filter by notebook name (partial match)'),
  sectionName: z.string().optional().describe('Filter by section name (partial match)'),
  dateFrom: z.iso
    .datetime()
    .optional()
    .describe('Filter pages created/modified from this datetime (ISO 8601)'),
  dateTo: z.iso
    .datetime()
    .optional()
    .describe('Filter pages created/modified until this datetime (ISO 8601)'),
  limit: z
    .number()
    .int()
    .min(1)
    .max(100)
    .default(10)
    .describe('Maximum number of results to return'),
});

const SearchResultSchema = z.object({
  id: z.string().describe('Unique content ID'),
  chunkId: z.string().optional().describe('Chunk ID within the content'),
  title: z.string().describe('Page title'),
  key: z.string().optional().describe('Content key'),
  text: z.string().describe('The relevant passage'),
  url: z.string().optional().describe('Fallback URL for the page'),
  oneNoteWebUrl: z
    .string()
    .optional()
    .describe('Direct link to open this page in OneNote. Use this for markdown links.'),
  notebookName: z.string().optional().describe('Notebook name'),
  sectionName: z.string().optional().describe('Section name'),
  createdDateTime: z.string().optional().describe('Page creation date'),
  lastModifiedDateTime: z.string().optional().describe('Page last modified date'),
  score: z.number().optional().describe('Relevance score'),
});

const SyncStatusSchema = z.object({
  lastSyncedAt: z
    .string()
    .nullable()
    .describe('ISO 8601 timestamp of the last completed sync, or null if never synced'),
  secondsSinceLastSync: z
    .number()
    .nullable()
    .describe('Seconds elapsed since the last sync completed, or null if never synced'),
  dataFreshnessNote: z
    .string()
    .describe(
      'A human-readable note about data freshness. Relay this to the user as-is. Do not call other tools based on this note.',
    ),
});

const SearchOutputSchema = z.object({
  results: z
    .array(SearchResultSchema)
    .describe('Search results. Use [N] to cite result at index N (e.g., [0], [1])'),
  syncStatus: SyncStatusSchema.describe(
    'Information about the last sync. Relay the dataFreshnessNote to the user so they know how current the data is. Do not automatically call other tools based on this information.',
  ),
});

@Injectable()
export class SearchOneNoteTool {
  private readonly logger = new Logger(SearchOneNoteTool.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly contentService: UniqueContentService,
    private readonly scopeService: UniqueScopeService,
    private readonly deltaService: OneNoteDeltaService,
    private readonly syncService: OneNoteSyncService,
  ) {}

  @Tool({
    name: 'search_onenote',
    title: 'Search OneNote Pages',
    description:
      'Search for content within synced OneNote pages using semantic search. Returns relevant passages that can be cited using [N] notation.',
    parameters: SearchInputSchema,
    outputSchema: SearchOutputSchema,
    annotations: {
      title: 'Search OneNote Pages',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'search',
      'unique.app/system-prompt':
        'Use this tool only when the user explicitly asks to search, find, or look up existing content in their OneNote notebooks. ' +
        'Do not use this tool before creating or updating pages. ' +
        'Cite results using [N] where N is the array index.',
      'unique.app/tool-format-information':
        'Always include a clickable markdown link [open document](oneNoteWebUrl) using the oneNoteWebUrl field for every OneNote page you mention or reference in your response. ' +
        'Always relay syncStatus.dataFreshnessNote to the user — it explains data freshness, ongoing syncs, and any Microsoft API throttling.',
    },
  })
  @Span()
  public async searchOneNote(
    input: z.infer<typeof SearchInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof SearchOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    this.logger.log(
      {
        userProfileId,
        notebookName: input.notebookName,
        sectionName: input.sectionName,
        dateFrom: input.dateFrom,
        dateTo: input.dateTo,
        limit: input.limit,
      },
      'Tool search_onenote called',
    );

    try {
      const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });
      const userScope = await this.scopeService.createScope(rootScopeId, userProfileId, false);
      const searchRequest = this.buildSearchRequest(rootScopeId, userScope.id, input);

      const { searchString: _q, ...redactedRequest } = searchRequest;
      this.logger.log(
        {
          userProfileId,
          rootScopeId,
          userScopeId: userScope.id,
          searchRequest: redactedRequest,
        },
        'Executing search with resolved parameters',
      );

      const result = await this.contentService.search(searchRequest);

      this.logger.log(
        { userProfileId, resultCount: result.data.length },
        'Search completed',
      );

      const results = result.data.map((item) => {
        const metadata = item.metadata as Record<string, unknown> | null;

        return {
          id: item.id,
          chunkId: item.chunkId,
          title: item.title ?? 'Untitled Page',
          key: item.key,
          text: item.text,
          url: `unique://content/${item.id}`,
          oneNoteWebUrl:
            typeof metadata?.oneNoteWebUrl === 'string'
              ? metadata.oneNoteWebUrl
              : undefined,
          notebookName:
            typeof metadata?.notebookName === 'string' ? metadata.notebookName : undefined,
          sectionName:
            typeof metadata?.sectionName === 'string' ? metadata.sectionName : undefined,
          createdDateTime:
            typeof metadata?.createdDateTime === 'string' ? metadata.createdDateTime : undefined,
          lastModifiedDateTime:
            typeof metadata?.lastModifiedDateTime === 'string'
              ? metadata.lastModifiedDateTime
              : undefined,
          score: undefined,
        };
      });

      const syncStatus = await this.buildSyncStatus(userProfileId);

      return { results, syncStatus };
    } catch (error) {
      const safeError = extractSafeGraphError(error);
      this.logger.error({ userProfileId, ...safeError }, 'Search failed');
      return {
        results: [],
        syncStatus: {
          lastSyncedAt: null,
          secondsSinceLastSync: null,
          dataFreshnessNote: `Search failed: ${safeError.message}`,
        },
      };
    }
  }

  private async buildSyncStatus(
    userProfileId: string,
  ): Promise<z.infer<typeof SyncStatusSchema>> {
    const deltaStatus = await this.deltaService.getDeltaStatus(userProfileId);
    const isSyncing = this.syncService.isSyncRunning(userProfileId);
    const throttleRemainingMs = GlobalThrottleMiddleware.currentThrottleRemainingMs(userProfileId);

    const extras: string[] = [];
    if (isSyncing) {
      extras.push('A background sync is currently running — the latest data may not be reflected yet. Try searching again in a moment.');
    }
    if (throttleRemainingMs > 0) {
      const sec = Math.round(throttleRemainingMs / 1000);
      extras.push(`Microsoft OneNote is temporarily rate-limiting requests. Background syncs may be delayed by up to ${sec}s. This resolves on its own.`);
    }

    if (!deltaStatus?.lastSyncedAt) {
      const note = [
        'No sync has been completed yet. Search results may be empty.',
        ...extras,
      ].filter(Boolean).join(' ');

      return {
        lastSyncedAt: null,
        secondsSinceLastSync: null,
        dataFreshnessNote: note,
      };
    }

    const secondsSinceLastSync = Math.round(
      (Date.now() - deltaStatus.lastSyncedAt.getTime()) / 1000,
    );

    const parts: string[] = [];
    if (secondsSinceLastSync <= 120) {
      parts.push('Data is up to date.');
    } else {
      parts.push(
        `The last sync was ${Math.round(secondsSinceLastSync / 60)} minutes ago. ` +
        'Recent changes in OneNote may not be reflected yet.',
      );
    }
    parts.push(...extras);

    return {
      lastSyncedAt: deltaStatus.lastSyncedAt.toISOString(),
      secondsSinceLastSync,
      dataFreshnessNote: parts.join(' '),
    };
  }

  private buildSearchRequest(
    rootScopeId: string,
    userScopeId: string,
    input: z.infer<typeof SearchInputSchema>,
  ): PublicSearchRequest {
    const userFolderPath = `uniquepathid://${rootScopeId}/${userScopeId}`;

    const conditions: MetadataFilter[] = [
      {
        path: ['folderIdPath'],
        operator: UniqueQLOperator.CONTAINS,
        value: userFolderPath,
      },
    ];

    if (input.notebookName) {
      conditions.push({
        path: ['metadata', 'notebookName'],
        operator: UniqueQLOperator.CONTAINS,
        value: input.notebookName,
      });
    }

    if (input.sectionName) {
      conditions.push({
        path: ['metadata', 'sectionName'],
        operator: UniqueQLOperator.CONTAINS,
        value: input.sectionName,
      });
    }

    if (input.dateFrom) {
      conditions.push({
        path: ['metadata', 'lastModifiedDateTime'],
        operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
        value: input.dateFrom,
      });
    }

    if (input.dateTo) {
      conditions.push({
        path: ['metadata', 'lastModifiedDateTime'],
        operator: UniqueQLOperator.LESS_THAN_OR_EQUAL,
        value: input.dateTo,
      });
    }

    return {
      searchString: input.query,
      searchType: SearchType.COMBINED,
      limit: input.limit,
      metaDataFilter: { and: conditions },
    };
  }
}
