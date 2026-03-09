import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import type { UniqueConfigNamespaced } from '~/config';
import {
  type MetadataFilter,
  type PublicSearchRequest,
  SearchType,
  UniqueQLOperator,
} from '~/unique/unique.dtos';
import { UniqueContentService } from '~/unique/unique-content.service';
import { UniqueUserMappingService } from '~/unique/unique-user-mapping.service';

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
  scoreThreshold: z
    .number()
    .min(0)
    .max(1)
    .optional()
    .describe('Minimum relevance score threshold (0-1)'),
});

const SearchResultSchema = z.object({
  id: z.string().describe('Unique content ID'),
  chunkId: z.string().optional().describe('Chunk ID within the content'),
  title: z.string().describe('Page title'),
  key: z.string().optional().describe('Content key'),
  text: z.string().describe('The relevant passage'),
  url: z.string().optional().describe('OneNote web URL for the page'),
  notebookName: z.string().optional().describe('Notebook name'),
  sectionName: z.string().optional().describe('Section name'),
  createdDateTime: z.string().optional().describe('Page creation date'),
  lastModifiedDateTime: z.string().optional().describe('Page last modified date'),
  score: z.number().optional().describe('Relevance score'),
});

const SearchOutputSchema = z.object({
  results: z
    .array(SearchResultSchema)
    .describe('Search results. Use [N] to cite result at index N (e.g., [0], [1])'),
});

@Injectable()
export class SearchOneNoteTool {
  private readonly logger = new Logger(SearchOneNoteTool.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly contentService: UniqueContentService,
    private readonly userMapping: UniqueUserMappingService,
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
        'Use this tool to search OneNote pages. Cite results using [N] where N is the array index.',
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

    const scopeContext = await this.userMapping.resolve(userProfileId);
    const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });
    const searchRequest = this.buildSearchRequest(rootScopeId, input);

    const result = await this.contentService.scopedSearch(searchRequest, scopeContext);

    const results = result.data.map((item) => {
      const metadata = item.metadata as Record<string, unknown> | null;

      return {
        id: item.id,
        chunkId: item.chunkId,
        title: item.title ?? 'Untitled Page',
        key: item.key,
        text: item.text,
        url:
          typeof metadata?.oneNoteWebUrl === 'string'
            ? metadata.oneNoteWebUrl
            : `unique://content/${item.id}`,
        notebookName:
          typeof metadata?.notebookName === 'string' ? metadata.notebookName : undefined,
        sectionName: typeof metadata?.sectionName === 'string' ? metadata.sectionName : undefined,
        createdDateTime:
          typeof metadata?.createdDateTime === 'string' ? metadata.createdDateTime : undefined,
        lastModifiedDateTime:
          typeof metadata?.lastModifiedDateTime === 'string'
            ? metadata.lastModifiedDateTime
            : undefined,
        score: undefined,
      };
    });

    this.logger.debug({ userProfileId, resultCount: results.length }, 'Completed OneNote search');

    return { results };
  }

  private buildSearchRequest(
    rootScopeId: string,
    input: z.infer<typeof SearchInputSchema>,
  ): PublicSearchRequest {
    const conditions: MetadataFilter[] = [
      {
        path: ['folderIdPath'],
        operator: UniqueQLOperator.CONTAINS,
        value: `uniquepathid://${rootScopeId}`,
      },
      {
        path: ['mimeType'],
        operator: UniqueQLOperator.EQUALS,
        value: 'text/html',
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
      searchType: SearchType.VECTOR,
      limit: input.limit,
      scoreThreshold: input.scoreThreshold,
      metaDataFilter: { and: conditions },
    };
  }
}
