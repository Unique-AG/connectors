import assert from 'node:assert';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, directories, directoriesSync, userProfiles } from '~/db';
import { getRootScopeExternalId } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

@Injectable()
export class RemoveRootScopeAndDirectoriesCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  public async run(userProfileTypeId: UserProfileTypeID): Promise<void> {
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileTypeId.toString()),
    });
    assert.ok(userProfile, `User profile not found for: ${userProfileTypeId.toString()}`);

    await this.db
      .delete(directoriesSync)
      .where(eq(directoriesSync.userProfileId, userProfile.id))
      .execute();

    await this.db
      .delete(directories)
      .where(eq(directories.userProfileId, userProfile.id))
      .execute();

    const rootScopeExists = await this.uniqueApi.scopes.getByExternalId(
      getRootScopeExternalId(userProfile.providerUserId),
    );
    if (rootScopeExists) {
      await this.uniqueApi.scopes.delete(rootScopeExists.id, {
        recursive: true,
      });
    }
  }
}
