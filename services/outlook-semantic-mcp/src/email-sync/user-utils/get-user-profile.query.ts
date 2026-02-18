import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { TraceService } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, UserProfile, userProfiles } from '~/drizzle';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';

@Injectable()
export class GetUserProfileQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly trace: TraceService,
  ) {}

  public async run(
    userProfileId: UserProfileTypeID,
  ): Promise<NonNullishProps<UserProfile, 'email'>> {
    const span = this.trace.getSpan();
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId.toString()),
    });
    assert.ok(userProfile, `User Profile missing userProfileId: ${userProfileId}`);
    span?.setAttribute('user_profile_id', userProfile.id);
    const email = userProfile.email;
    assert.ok(email, `User Profile with id:${userProfile.id} has no email ${email}`);

    return { ...userProfile, email };
  }
}
