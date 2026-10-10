import { Injectable, Logger } from '@nestjs/common';
import { isNullish } from 'remeda';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { sanitizeError } from '../utils/normalize-error';
import { FindFilesWithExpectedLocationQuery } from './find-files-with-expected-location.query';
import type { SharepointSyncContext } from './sharepoint-sync-context.interface';

interface Input {
  updatedFileKeys: string[];
  items: SharepointContentItem[];
  scopes: ScopeWithPath[] | null;
  context: SharepointSyncContext;
}

@Injectable()
export class MoveUpdatedFilesToExpectedScopeCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly uniqueFilesService: UniqueFilesService,
    private readonly findFilesWithExpectedLocationQuery: FindFilesWithExpectedLocationQuery,
  ) {}

  // Returns the file-diff keys whose move failed. Commands normally return nothing; this one
  // returns those keys so the caller can leave the items out of the cycle. Upserting them would
  // create a second content record in the new scope while the original stays in the old one.
  // Their updatedAt is still newer than the stored copy, so the next sync retries the move.
  public async execute(input: Input): Promise<ReadonlySet<string>> {
    const { updatedFileKeys, items, scopes, context } = input;

    if (isNullish(scopes) || scopes.length === 0 || updatedFileKeys.length === 0) {
      return new Set();
    }

    const logPrefix = `[Site: ${context.siteConfig.siteId}]`;
    const files = await this.findFilesWithExpectedLocationQuery.execute({
      diffKeys: updatedFileKeys,
      items,
      scopes,
      context,
    });
    const keysToLeaveOut = new Set<string>();

    for (const file of files) {
      if (file.currentScopeId === file.expectedScopeId) {
        continue;
      }

      try {
        await this.uniqueFilesService.moveFile(
          file.contentId,
          file.expectedScopeId,
          file.expectedUrl,
        );
      } catch (error) {
        this.logger.error({
          msg: `${logPrefix} Failed to move updated file ${file.contentId} to scope ${file.expectedScopeId}`,
          fileKey: file.key,
          error: sanitizeError(error),
        });
        keysToLeaveOut.add(file.diffKey);
      }
    }

    return keysToLeaveOut;
  }
}
