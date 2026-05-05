import { z } from 'zod/v4';
import { inboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { json } from '~/utils/zod';

export const mcpIngestionConfig = z.object({
  mcpBackend: z.literal(`MicrosoftGraphAndUniqueApi`),
  ingestionDefaultMailFilters: json(inboxConfigurationMailFilters).describe(
    'Default mail filters applied when syncing emails (e.g. {"retentionWindowInDays":95, "ignoredSenders": [], "ignoredContents": [] }). ',
  ),
  ingestionFullSyncRecoveryCron: z
    .string()
    .prefault('*/2 * * * *')
    .describe('Cron schedule for full sync recovery. Default every 2 minutes'),
  ingestionLiveCatchupRecovery: z
    .string()
    .prefault('*/5 * * * *')
    .describe('Cron schedule for full sync recovery. Default every 5 minutes'),
  ingestionDeleteInboxRecoveryCron: z
    .string()
    .prefault('*/5 * * * *')
    .describe('Cron schedule for full sync recovery. Default every 5 minutes'),
  // During our tests we noticed that if a user with a lot of emails in their inbox drags and drops a bunch of emails in another folder
  // we will lose this emails. This is because office365 is a distributed system and the rely on eventul concistency which means. You
  // can query via {{updatedAt}} le {someDate} and get 5 messages but and in the next second you query again and you get 10 messages
  // because the server which process the message stamps the {{updatedAt}} it sounds totally stupid but this is how they do it, they
  // rely on eventual concistency and they advise monitoring each folder which is just madness for our case. So an overlapping window
  // is advised if you use dates for high polling. The problem with this is that we do not know how much we need to put here a short
  // chat with claude about this yealded nothing claude says this should be something small max to be minutes. Gemini on the other hand
  // suggested something like this:
  // 1.  60 seconds if you agree to lose some messages
  // 2. 2-3 minutes you will get almost all messages it's a very low chance to lose anything
  // 3.   5 minutes you are 99% you get everything if there are big outages you will probably lose some messages but the change is quite low
  ingestionLiveCatchupRecheckOverlappingWindowMinutes: z.coerce
    .number()
    .min(10)
    .prefault(10)
    .describe('How many minutes should each live catchup run overlap the previous one'),
  ingestionLiveCatchupOverlappingWindowMinutes: z.coerce
    .number()
    .min(2)
    .prefault(3)
    .describe('How many minutes should each live catchup run overlap the previous one'),
});
