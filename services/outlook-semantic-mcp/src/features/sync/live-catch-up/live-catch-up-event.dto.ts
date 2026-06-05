import z from 'zod/v4';

export const LiveCatchUpExecutEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.live-catch-up.execute'),
  payload: z.union([
    z.object({
      /** @deprecated - transitioning to userProfileId for a cleaner model without subscription coupling */
      subscriptionId: z.string(),
      userProfileId: z.string().optional(),
      notificationReceivedAt: z.iso.datetime().optional(),
    }),
    z.object({
      subscriptionId: z.string().optional(),
      userProfileId: z.string(),
      notificationReceivedAt: z.iso.datetime().optional(),
    }),
  ]),
});

export const LiveCatchUpReadyRecheckEventDto = z.object({
  type: z.literal('unique.outlook-semantic-mcp.live-catch-up.ready-recheck'),
  payload: z.union([
    z.object({
      /** @deprecated - transitioning to userProfileId for a cleaner model without subscription coupling */
      subscriptionId: z.string(),
      userProfileId: z.string().optional(),
    }),
    z.object({
      subscriptionId: z.string().optional(),
      userProfileId: z.string(),
    }),
  ]),
});

export const LiveCatchUpEventDto = z.discriminatedUnion('type', [
  LiveCatchUpExecutEventDto,
  LiveCatchUpReadyRecheckEventDto,
]);
