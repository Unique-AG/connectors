import z from 'zod/v4';

/**
 * Represents a category by which a user can group Outlook items such as messages and events.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/outlookcategory?view=graph-rest-1.0
 */
export const OutlookCategory = z.object({
  id: z.string(),
  displayName: z.string(),
  color: z.string(),
});

export type OutlookCategory = z.infer<typeof OutlookCategory>;
