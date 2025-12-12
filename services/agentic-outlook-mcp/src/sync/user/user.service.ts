import { Inject, Injectable, Logger } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { eq } from 'drizzle-orm';
import { TypeID } from 'typeid-js';
import { BatchProcessor } from '../../batch/batch-processor.decorator';
import {
  DRIZZLE,
  DrizzleDatabase,
  UserUpdateZod,
  userProfiles,
  userUpdateSchemaCamelized,
} from '../../drizzle';
import { FolderEvents, FolderSyncEvent } from '../folder/folder.events';

@Injectable()
export class UserService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  @BatchProcessor({ table: 'user_profiles', operation: 'PUT' })
  public async onPut(
    userProfileId: TypeID<'user_profile'>,
    id: string,
    data?: Record<string, unknown>,
  ) {
    this.logger.warn({
      msg: 'This should never be called by the frontend, as the user profile is created by the backend.',
      userProfileId,
      id,
      data,
    });
  }

  @BatchProcessor({ table: 'user_profiles', operation: 'PATCH', schema: userUpdateSchemaCamelized })
  public async onPatch(userProfileId: TypeID<'user_profile'>, id: string, data?: UserUpdateZod) {
    if (!data) return;
    if (id !== userProfileId.toString()) throw new Error('User profile ID mismatch');

    await this.db
      .update(userProfiles)
      .set(data)
      .where(eq(userProfiles.id, userProfileId.toString()));

    // When sync is enabled, we catch or refresh all folders
    const syncEnabled = data.syncActivatedAt && !data.syncDeactivatedAt;
    if (syncEnabled) {
      this.logger.debug({ msg: 'Sync enabled, syncing folders' });
      this.eventEmitter.emit(FolderEvents.FolderSync, new FolderSyncEvent(userProfileId));
    }

    this.logger.log({
      msg: 'User profile patched',
      userProfileId: userProfileId.toString(),
      id,
      data,
      syncEnabled,
    });
  }

  @BatchProcessor({ table: 'user_profiles', operation: 'DELETE' })
  public async onDelete(
    userProfileId: TypeID<'user_profile'>,
    id: string,
    data?: Record<string, unknown>,
  ) {
    this.logger.warn({
      msg: 'This should not have been called. Frontend does not support deleting user profiles.',
      userProfileId,
      id,
      data,
    });
  }
}
