import { Inject, Injectable } from '@nestjs/common';
import { type FeaturesConfig, featuresConfig } from '~/config';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from './get-user-profile.query';

type MailboxAccess = { allowed: true } | { allowed: false; message: string };

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
    const { email, username } = await this.getUserProfileQuery.run(userProfileId);
    // The mailbox goes to Graph as given, so it is compared as given: the address or the UPN.
    const own = [email, username].map((address) => address.toLowerCase());
    if (own.includes(mailbox.toLowerCase())) {
      return { allowed: true };
    }
    return {
      allowed: false,
      message: `This server works only with your own mailbox (${email}). Call the tool again without \`mailbox\`.`,
    };
  }
}
