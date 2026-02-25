import assert from 'node:assert';
import { SearchType, type UniqueApiClient } from '@unique-ag/unique-api';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, type DrizzleDatabase, userProfiles } from '~/db';
import { MessageMetadata } from '~/email-sync/mail-ingestion/utils/get-metadata-from-message';
import { getRootScopeExternalId } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { buildSearchFilter, SearchEmailsInputSchema } from './search-conditions.dto';

export interface SearchEmailResult {
  id: string;
  emailId: string;
  folderId: string;
  title: string;
  from: string;
  receivedDateTime: string | null;
  text: string;
  url: string | undefined;
}

@Injectable()
export class SearchEmailsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Span()
  public async run(
    userProfileId: string,
    input: z.infer<typeof SearchEmailsInputSchema>,
  ): Promise<SearchEmailResult[]> {
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User profile not found: ${userProfileId}`);
    assert.ok(userProfile.providerUserId, `providerUserId missing for: ${userProfileId}`);

    const rootScope = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalId(userProfile.providerUserId),
    );
    assert.ok(rootScope, `Root scope not found for user: ${userProfile.providerUserId}`);

    const uniqueQlMetadataFilter = buildSearchFilter(input.conditions);
    this.logger.log({ msg: `Unique Ql Query`, prompt: input.search, uniqueQlMetadataFilter });
    const searchResult = await this.uniqueApi.content.search({
      prompt: input.search,
      searchType: SearchType.VECTOR,
      scopeIds: [rootScope.id],
      metaDataFilter: uniqueQlMetadataFilter,
      limit: input.limit,
      scoreThreshold: input.scoreThreshold,
    });

    return searchResult.map((item) => {
      const metadata = item.metadata as MessageMetadata | undefined;
      return {
        title: item.title ?? '',
        id: item.id,
        text: item.text,
        url: item.url ?? undefined,
        emailId: metadata?.id ?? '',
        folderId: metadata?.parentFolderId ?? '',
        from: metadata?.['from.emailAddress'] ?? '',
        receivedDateTime: metadata?.receivedDateTime ?? '',
      };
    });
  }
}
