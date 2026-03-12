import { Logger } from '@nestjs/common';
import { InboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { traceEvent } from '~/features/tracing.utils';

const logger = new Logger('shouldSkipEmail');

interface EmailInput {
  from?: { emailAddress?: { address?: string } | null } | null;
  subject?: string | null;
  uniqueBody?: { content?: string } | null;
  createdDateTime?: string;
}

export type SkipResult =
  | { skip: false }
  | {
      skip: true;
      reason: 'ignoredBefore' | 'ignoredSenders' | 'ignoredContents';
      matchedPattern?: string;
    };

export function shouldSkipEmail(
  email: EmailInput,
  filters: InboxConfigurationMailFilters,
  context: { userProfileId: string },
): SkipResult {
  try {
    if (filters.ignoredBefore && email.createdDateTime) {
      if (new Date(email.createdDateTime) < filters.ignoredBefore) {
        return { skip: true, reason: 'ignoredBefore' };
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
