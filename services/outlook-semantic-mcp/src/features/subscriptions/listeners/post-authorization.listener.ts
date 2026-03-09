import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SubscriptionCreateService } from '../subscription-create.service';

@Injectable()
export class PostAuthorizationListener {
  private readonly logger = new Logger(PostAuthorizationListener.name);

  public constructor(private readonly subscriptionCreateService: SubscriptionCreateService) {}

  @OnEvent('user.authorized')
  public async onUserAuthorized(payload: { userProfileId: string }): Promise<void> {
    try {
      const result = await this.subscriptionCreateService.subscribe(
        convertUserProfileIdToTypeId(payload.userProfileId),
      );
      this.logger.log({
        msg: 'Subscription outcome after user authorization',
        userProfileId: payload.userProfileId,
        status: result.status,
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed to subscribe user after authorization',
        userProfileId: payload.userProfileId,
        error,
      });
    }
  }
}
