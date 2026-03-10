import { Logger } from '@nestjs/common';
import { InboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceEvent } from '~/features/tracing.utils';

const logger = new Logger('shouldSkipEmail');

type EmailInput = {
  from?: { emailAddress?: { address?: string } | null } | null;
  subject?: string;
  uniqueBody?: { content?: string } | null;
  createdDateTime?: string;
};

type SkipResult =
  | { skip: false }
  | { skip: true; reason: 'dateFrom' | 'ignoredSenders' | 'ignoredContents'; matchedPattern?: string };

export function shouldSkipEmail(
  email: EmailInput,
  filters: InboxConfigurationMailFilters,
  context: { userProfileId: string },
): SkipResult {
  try {
    if (filters.dateFrom && email.createdDateTime) {
      if (new Date(email.createdDateTime) < filters.dateFrom) {
        return { skip: true, reason: 'dateFrom' };
      }
    }

    for (const pattern of filters.ignoredSenders) {
      if (pattern.test(email.from?.emailAddress?.address ?? '')) {
        return { skip: true, reason: 'ignoredSenders', matchedPattern: pattern.toString() };
      }
    }

    for (const pattern of filters.ignoredContents) {
      if (pattern.test(email.subject ?? '') || pattern.test(email.uniqueBody?.content ?? '')) {
        return { skip: true, reason: 'ignoredContents', matchedPattern: pattern.toString() };
      }
    }

    return { skip: false };
  } catch (error) {
    const attrs = { userProfileId: context.userProfileId };
    logger.error({ message: 'shouldSkipEmail failed — failing open', error, ...attrs });
    traceEvent('shouldSkipEmail.error', attrs);
    return { skip: false };
  }
}
