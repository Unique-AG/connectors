import z from 'zod/v4';

/**
 * Request body for subscribing to change notifications on a Microsoft Graph resource.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0
 */
export const CreateSubscriptionRequest = z.object({
  changeType: z.string(),
  resource: z.string(),
  notificationUrl: z.string(),
  lifecycleNotificationUrl: z.string().optional(),
  expirationDateTime: z.instanceof(Date).transform((d) => d.toISOString()),
  clientState: z.string().optional(),
});

/**
 * Request body for renewing a subscription before it expires.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/subscription-update?view=graph-rest-1.0
 */
export const UpdateSubscriptionRequest = z.object({
  expirationDateTime: z.instanceof(Date).transform((d) => d.toISOString()),
});

export type CreateSubscriptionRequest = z.input<typeof CreateSubscriptionRequest>;
export type UpdateSubscriptionRequest = z.input<typeof UpdateSubscriptionRequest> & {
  subscriptionId: string;
};
