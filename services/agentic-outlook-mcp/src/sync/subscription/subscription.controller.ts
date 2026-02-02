import { Body, Controller, Post, Query } from '@nestjs/common';
import { ChangeNotificationCollectionDto } from './dto/change-notification-collection.dto';
import { SubscriptionService } from './subscription.service';

@Controller('subscriptions')
export class SubscriptionController {
  public constructor(private readonly subscriptionService: SubscriptionService) {}

  @Post('notification')
  public async subscription(
    @Body() body: ChangeNotificationCollectionDto,
    @Query('validationToken') validationToken?: string,
  ) {
    if (validationToken) return validationToken;
    return this.subscriptionService.onNotification(body);
  }

  @Post('lifecycle')
  public async lifecycle(
    @Body() body: ChangeNotificationCollectionDto,
    @Query('validationToken') validationToken?: string,
  ) {
    if (validationToken) return validationToken;
    return this.subscriptionService.onLifecycle(body);
  }
}
