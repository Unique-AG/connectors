import { z } from 'zod/v4';

// TODO: Refine this concept

export const subscriptionMailFilters = z.object({
  dateFrom: z.coerce.date(),
});

export type SubscriptionMailFilters = z.infer<typeof subscriptionMailFilters>;
