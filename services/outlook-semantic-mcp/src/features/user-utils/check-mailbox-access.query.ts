import { Inject, Injectable } from '@nestjs/common';
import { type FeaturesConfig, featuresConfig } from '~/config';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from './get-user-profile.query';

export type MailboxAccess = { allowed: true } | { allowed: false; message: string };

// Without shared mailboxes the server is not granted the `.Shared` permissions, so another
// person's mailbox is refused before Graph is called.
@Injectable()
export class CheckMailboxAccessQuery {
  public constructor(
    @Inject(featuresConfig.KEY) private readonly features: FeaturesConfig,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  public async run(
    userProfileId: UserProfileTypeID,
    mailbox: string | undefined,
  ): Promise<MailboxAccess> {
    if (mailbox === undefined || this.features.sharedMailboxes) {
      return { allowed: true };
    }
    const { email } = await this.getUserProfileQuery.run(userProfileId);
    if (mailbox.trim().toLowerCase() === email.toLowerCase()) {
      return { allowed: true };
    }
    return {
      allowed: false,
      message: `This server works only with your own mailbox (${email}). Call the tool again without \`mailbox\`.`,
    };
  }
}
