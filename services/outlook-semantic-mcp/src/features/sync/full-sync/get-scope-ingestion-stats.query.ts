import { IngestionState, UniqueApiClient } from '@unique-ag/unique-api';
import { asAllOptions } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { omit, sumBy, values } from 'remeda';
import { DRIZZLE, DrizzleDatabase, userProfiles } from '~/db';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';

export type ScopeIngestionStats =
  | { ok: true; rootScopeId: string; failed: number; finished: number; inProgress: number }
  | { ok: false; reason: string };

type FailedIngestionStates = Exclude<
  IngestionState,
  | IngestionState.CheckingIntegrity
  | IngestionState.Finished
  | IngestionState.IngestionChunking
  | IngestionState.IngestionEmbedding
  | IngestionState.IngestionReading
  | IngestionState.MalwareScanning
  | IngestionState.MetadataValidation
  | IngestionState.Queued
  | IngestionState.RebuildingMetadata
  | IngestionState.RecreatingVecetordbIndex
  | IngestionState.Retrying
  | IngestionState.ReEmbedding
  | IngestionState.ReIngesting
  | IngestionState.ExtractingMetadata
>;

const FAILED_INGESTION_STATUSES = asAllOptions<FailedIngestionStates>()([
  IngestionState.Failed,
  IngestionState.FailedCreatingChunks,
  IngestionState.FailedEmbedding,
  IngestionState.FailedGettingFile,
  IngestionState.FailedImage,
  IngestionState.FailedMalwareFound,
  IngestionState.FailedMetadataValidation,
  IngestionState.FailedMalwareScanTimeout,
  IngestionState.FailedParsing,
  IngestionState.FailedRedelivered,
  IngestionState.FailedTimeout,
  IngestionState.FailedTooLessContent,
  IngestionState.FailedTableLimitExceeded,
]);

@Injectable()
export class GetScopeIngestionStatsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Span()
  public async run(userProfileId: string): Promise<ScopeIngestionStats> {
    try {
      const userProfile = await this.db.query.userProfiles.findFirst({
        where: eq(userProfiles.id, userProfileId),
      });
      if (!userProfile?.providerUserId) {
        return { ok: false, reason: 'no-provider-user-id' };
      }

      const rootScopeExternalId = getRootScopeExternalIdForUser(userProfile.providerUserId);
      const rootScope = await this.uniqueApi.scopes.getByExternalId(rootScopeExternalId);
      if (!rootScope) {
        return { ok: false, reason: 'no-root-scope' };
      }

      const rawStats = await this.uniqueApi.ingestion.getIngestionStats(rootScope.id);

      const failed = sumBy(FAILED_INGESTION_STATUSES, (status) => rawStats[status] ?? 0);
      const finished = rawStats[IngestionState.Finished] ?? 0;
      const inProgress = sumBy(
        values(omit(rawStats, [...FAILED_INGESTION_STATUSES, IngestionState.Finished])),
        (item) => item ?? 0,
      );

      this.logger.debug({ userProfileId, inProgress, msg: 'Scope ingestion stats retrieved' });
      return { ok: true, rootScopeId: rootScope.id, failed, finished, inProgress };
    } catch (error) {
      this.logger.warn({ err: error, userProfileId, msg: 'Failed to fetch scope ingestion stats' });
      return { ok: false, reason: 'fetch-failed' };
    }
  }
}
