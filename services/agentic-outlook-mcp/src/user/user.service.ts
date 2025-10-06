import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { eq } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import * as z from 'zod';
import { BatchProcessor } from '../batch/batch-processor.decorator';
import { DRIZZLE, DrizzleDatabase, userProfiles, userUpdateSchema } from '../drizzle';
import { FolderEvents, FolderSyncEvent } from '../folder/folder.events';
import { camelizeKeys } from '../utils/case-converter';

const userUpdateSchemaCamelized = z.unknown().transform(camelizeKeys).pipe(userUpdateSchema);

@Injectable()
export class UserService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  @BatchProcessor({ table: 'user_profiles', operation: 'PUT' })
  public async onPut(userProfileId: TypeID<'user_profile'>, data?: Record<string, unknown>) {
    this.logger.warn({
      msg: 'This should never be called by the frontend, as the user profile is created by the backend.',
      userProfileId,
      data,
    });
  }

  @BatchProcessor({ table: 'user_profiles', operation: 'PATCH' })
  public async onPatch(userProfileId: TypeID<'user_profile'>, data?: Record<string, unknown>) {
    const parsedData = userUpdateSchemaCamelized.parse(data);
    await this.db
      .update(userProfiles)
      .set(parsedData)
      .where(eq(userProfiles.id, userProfileId.toString()));

    // When sync is enabled, we catch or refresh all folders
    const syncEnabled = parsedData.syncActivatedAt && !parsedData.syncDeactivatedAt;
    if (syncEnabled) {
      this.logger.debug({ msg: 'Sync enabled, syncing folders' });
      this.eventEmitter.emit(FolderEvents.FolderSync, new FolderSyncEvent(userProfileId));
    }

    this.logger.log({
      msg: 'User profile patched',
      userProfileId: userProfileId.toString(),
      parsedData,
      syncEnabled,
    });
  }

  @BatchProcessor({ table: 'user_profiles', operation: 'DELETE' })
  public async onDelete(userProfileId: TypeID<'user_profile'>, data?: Record<string, unknown>) {
    this.logger.warn({
      msg: 'This should not have been called. Frontend does not support deleting user profiles.',
      userProfileId,
      data,
    });
  }
}
