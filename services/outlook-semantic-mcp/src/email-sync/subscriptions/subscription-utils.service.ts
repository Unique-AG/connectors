import path from 'node:path';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TraceService } from 'nestjs-otel';
import type { AppConfigNamespaced, MicrosoftConfigNamespaced } from '~/config';
import type { Redacted } from '~/utils/redacted';

@Injectable()
export class MailSubscriptionUtilsService {
  private readonly logger = new Logger(MailSubscriptionUtilsService.name);

  public constructor(
    private readonly config: ConfigService<AppConfigNamespaced & MicrosoftConfigNamespaced, true>,
    private readonly trace: TraceService,
  ) {}

  public isWebhookTrustedViaState(state: Redacted<string> | null): boolean {
    const webhookSecret = this.config.get('microsoft.webhookSecret', {
      infer: true,
    });

    const isTrusted = state !== null && state.value === webhookSecret.value;

    this.logger.debug(
      { isTrusted, hasState: state !== null },
      'Validating webhook authenticity using client state verification',
    );
    const span = this.trace.getSpan();
    span?.setAttribute('is_trusted', isTrusted);

    return isTrusted;
  }

  public getSubscriptionURLs(): {
    notificationUrl: URL;
    lifecycleNotificationUrl: URL;
  } {
    const publicWebhookUrl = this.config.get('microsoft.publicWebhookUrl', { infer: true });

    const notificationUrl = new URL(
      path.join(publicWebhookUrl.pathname, 'mail-subscription/notification'),
      publicWebhookUrl,
    );
    const lifecycleNotificationUrl = new URL(
      path.join(publicWebhookUrl.pathname, 'mail-subscription/lifecycle'),
      publicWebhookUrl,
    );

    this.logger.debug(
      {
        notificationUrl: notificationUrl.toString(),
        lifecycleNotificationUrl: lifecycleNotificationUrl.toString(),
      },
      'Generated webhook URLs for Microsoft Graph subscription endpoints',
    );

    return {
      notificationUrl,
      lifecycleNotificationUrl,
    };
  }

  public getNextScheduledExpiration(): Date {
    // NOTE: requires to be at least 2 hours in the future or we won't be getting lifecycle notifications
    // We technically could do with anything more than 1 hour, but to be safe we pick 2 hours to give more
    // buffer in case of delays. Lifecycle notifications are sent at some intervals before 15/45 minutes before expiration.
    // Those notifications are crucial to renew, remove and recreate subscriptions before they expire and we miss notifications completely.
    const lifecycleHoursRequired = 2;
    const targetHour = this.config.get('microsoft.subscriptionExpirationTimeHoursUTC', {
      infer: true,
    });

    const now = new Date();
    // NOTE: We synchronize all times to UTC to avoid disrupations during the day for incoming notifications
    // hooks because Microsoft Graph always sends a notification *only* if the artifact is created
    // while a subscription is active; otherwise, we miss the notification completely and we will never know.
    // Thus, we pick a time that is always outside of working hours to reduce the chance of missing notifications.
    // This is because _renewals_ keep a subscription active but _creations_ actually not, so if it eventually
    // expires during outside of working hours, the creation happen in a time where we would likely not miss anything.
    const nextSync = new Date(
      Date.UTC(
        now.getUTCFullYear(),
        now.getUTCMonth(),
        now.getUTCDate(),
        targetHour, // hour
        0, // minute
        0, // second
        0, // ms
      ),
    );

    // NOTE: we synchronise all of them to 1 day in advance at most because if we would do a longer window
    // each time a notification comes in, and a token is expired, we would try to keep getting data from the API
    // but it keeps failing (because token expired) and we would just spam with errors
    // - instead we renew daily, so that if anyone is expired, we get less "notification with expired token"
    // noise and we would see who has token expired on a daily basis at renewal.
    const nowHour = now.getUTCHours();
    const needsNextDay = nowHour >= targetHour || nowHour + lifecycleHoursRequired >= targetHour;
    if (needsNextDay) {
      nextSync.setUTCDate(nextSync.getUTCDate() + 1);
    }

    this.logger.debug(
      {
        now,
        nextSync,
      },
      'Calculated next scheduled subscription expiration time',
    );

    return nextSync;
  }

  public getWebhookSecret(): Redacted<string> {
    return this.config.get('microsoft.webhookSecret', {
      infer: true,
    });
  }
}
