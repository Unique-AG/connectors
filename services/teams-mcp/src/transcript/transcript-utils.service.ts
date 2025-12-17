import path from 'node:path';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TraceService } from 'nestjs-otel';
import type { AppConfigNamespaced, MicrosoftConfigNamespaced } from '~/config';
import type { Redacted } from '~/utils/redacted';

@Injectable()
export class TranscriptUtilsService {
  private readonly logger = new Logger(TranscriptUtilsService.name);

  public constructor(
    private readonly config: ConfigService<AppConfigNamespaced & MicrosoftConfigNamespaced, true>,
    private readonly trace: TraceService,
  ) {}

  public isWebhookTrustedViaState(state: Redacted<string> | null): boolean {
    const webhookSecret = this.config.get('microsoft.webhookSecret', {
      infer: true,
    });

    const isTrusted = state === null || state.value === webhookSecret.value;

    this.logger.debug({ isTrusted, hasState: state !== null }, 'webhook trust validation');
    const span = this.trace.getSpan();
    span?.setAttribute('isTrusted', isTrusted);

    return isTrusted;
  }

  public getSubscriptionURLs(): {
    notificationUrl: URL;
    lifecycleNotificationUrl: URL;
  } {
    const publicWebhookUrl = this.config.get('microsoft.publicWebhookUrl', { infer: true });

    const notificationUrl = new URL(
      path.join(publicWebhookUrl.pathname, 'transcript/notification'),
      publicWebhookUrl,
    );
    const lifecycleNotificationUrl = new URL(
      path.join(publicWebhookUrl.pathname, 'transcript/lifecycle'),
      publicWebhookUrl,
    );

    this.logger.debug(
      {
        notificationUrl: notificationUrl.toString(),
        lifecycleNotificationUrl: lifecycleNotificationUrl.toString(),
      },
      'subscription URLs generated',
    );

    return {
      notificationUrl,
      lifecycleNotificationUrl,
    };
  }

  public getNextScheduledExpiration(): Date {
    // NOTE: requires to be at least 2 hours in the future or we won't be getting lifecycle notifications
    const lifecycleHoursRequired = 2;
    const targetHour = 3; // TODO: can extract to a module option at somepoint

    const now = new Date();
    // build today's target (3:00:00.000 UTC)
    const nextThreeAM = new Date(
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

    const nowHour = now.getUTCHours();
    const needsNextDay = nowHour >= targetHour || nowHour + lifecycleHoursRequired >= targetHour;
    if (needsNextDay) {
      nextThreeAM.setUTCDate(nextThreeAM.getUTCDate() + 1);
    }

    this.logger.debug(
      {
        now,
        nextThreeAM,
      },
      'next scheduled expiration',
    );

    return nextThreeAM;
  }

  public getWebhookSecret(): Redacted<string> {
    return this.config.get('microsoft.webhookSecret', {
      infer: true,
    });
  }
}
