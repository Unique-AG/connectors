import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

export const ListCategoriesQueryOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  status: z.string().optional(),
  categories: z.array(z.string()).optional(),
  count: z.number().optional(),
});

export type ListCategoriesResult = z.infer<typeof ListCategoriesQueryOutputSchema>;

@Injectable()
export class ListCategoriesQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<ListCategoriesResult> {
    const userProfileIdString = userProfileId.toString();

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
    } catch (err) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to fetch categories from Microsoft Graph',
        err,
      });
      throw new InternalServerErrorException('Failed to fetch categories from Microsoft Graph');
    }
  }
}
