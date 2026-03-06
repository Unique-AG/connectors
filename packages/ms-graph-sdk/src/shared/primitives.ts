import z from 'zod/v4';

/** Codec that parses ISO 8601 datetime strings into Date objects. */
export const isoDatetimeToDate = (opts?: { offset?: boolean }) =>
  z.codec(opts?.offset ? z.iso.datetime({ offset: true }) : z.iso.datetime(), z.instanceof(Date), {
    decode: (value) => new Date(value),
    encode: (date) => date.toISOString(),
  });

/** Codec that parses URL strings into URL objects. */
export const stringToURL = () =>
  z.codec(z.url(), z.instanceof(URL), {
    decode: (value) => new URL(value),
    encode: (url) => url.href,
  });

/**
 * Represents identities of an actor in an activity.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/identityset?view=graph-rest-1.0
 */
export const IdentitySet = z.object({
  application: z.object({ id: z.string(), displayName: z.string().nullish() }).nullish(),
  device: z.object({ id: z.string(), displayName: z.string().nullish() }).nullish(),
  user: z
    .object({
      id: z.string(),
      displayName: z.string().nullish(),
      tenantId: z.string().nullish(),
    })
    .nullish(),
});

/**
 * Represents information about a user in the sending or receiving end of an event or message.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/recipient?view=graph-rest-1.0
 */
export const Recipient = z.object({
  emailAddress: z
    .object({
      address: z.string().optional(),
      name: z.string().optional(),
    })
    .optional(),
});

/**
 * Represents properties of the body of an item, such as a message, event or group post.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/itembody?view=graph-rest-1.0
 */
export const ItemBody = z.object({
  contentType: z.enum(['text', 'html']).optional(),
  content: z.string().optional(),
});

/**
 * Describes the date, time, and time zone of a point in time.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/datetimetimezone?view=graph-rest-1.0
 */
export const DateTimeTimeZone = z.object({
  dateTime: z.string(),
  timeZone: z.string(),
});
