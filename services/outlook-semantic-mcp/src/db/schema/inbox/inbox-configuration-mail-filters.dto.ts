import { z } from 'zod/v4';

export const inboxConfigurationMailFilters = z.object({
  dateFrom: z.coerce.date(),
});

export type InboxConfigurationMailFilters = z.infer<typeof inboxConfigurationMailFilters>;
