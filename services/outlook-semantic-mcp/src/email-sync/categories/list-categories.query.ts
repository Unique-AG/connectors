import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GetSubscriptionStatusQuery } from '~/email-sync/subscriptions/get-subscription-status.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

export type ListCategoriesResult =
  | { success: false; message: string }
  | { success: true; message: string; categories: string[]; count: number };

@Injectable()
export class ListCategoriesQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly graphClientFactory: GraphClientFactory,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCategoriesResult> {
    const userProfileIdString = userProfileId.toString();
    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileId);

    if (!subscriptionStatus.success) {
      this.logger.debug({
        userProfileId: userProfileIdString,
        msg: subscriptionStatus.message,
        status: subscriptionStatus.success,
      });
      return subscriptionStatus;
    }

    const categoryItems = await this.getCategoriesFromMicrosoft(userProfileIdString);
    const seen = new Set<string>();
    const categories: string[] = [];
    for (const item of categoryItems) {
      if (item.displayName && !seen.has(item.displayName)) {
        seen.add(item.displayName);
        categories.push(item.displayName);
      }
    }

    return {
      success: true,
      message:
        categories.length === 0
          ? 'No categories configured.'
          : `Found ${categories.length} categor${categories.length === 1 ? 'y' : 'ies'}.`,
      categories,
      count: categories.length,
    };
  }

  private async getCategoriesFromMicrosoft(
    userProfileIdString: string,
  ): Promise<{ displayName?: string }[]> {
    try {
      const client = this.graphClientFactory.createClientForUser(userProfileIdString);
      const response = await client.api('me/outlook/masterCategories').get();
      return response.value ?? [];
    } catch (error) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to fetch categories from Microsoft Graph',
        error,
      });
      throw new InternalServerErrorException('Failed to fetch categories from Microsoft Graph');
    }
  }
}
