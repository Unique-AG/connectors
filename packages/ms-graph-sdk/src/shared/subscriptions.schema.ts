import z from 'zod/v4';
import { isoDatetimeToDate, stringToURL } from './primitives';

/**
 * The type of change in the subscribed resource that raises a change notification.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0
 */
export const SubscriptionChangeType = z.enum(['created', 'updated', 'deleted']);

/**
 * The type of lifecycle event for a subscription.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/changenotification?view=graph-rest-1.0
 */
export const LifecycleEventType = z.enum([
  'subscriptionRemoved',
  'missed',
  'reauthorizationRequired',
]);

/**
 * A subscription that allows a client app to receive change notifications about changes
 * to data in Microsoft Graph.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0
 */
export const Subscription = z.object({
  id: z.string(),
  resource: z.string(),
  applicationId: z.string(),
  changeType: z.string(),
  clientState: z.string().nullable(),
  notificationUrl: stringToURL(),
  lifecycleNotificationUrl: stringToURL().nullable(),
  expirationDateTime: isoDatetimeToDate({ offset: true }),
  creatorId: z.string(),
  latestSupportedTlsVersion: z.string(),
  notificationUrlAppId: z.string().nullable(),
  notificationQueryOptions: z.string().nullable(),
  encryptionCertificate: z.string().nullable(),
  encryptionCertificateId: z.string().nullable(),
  includeResourceData: z.boolean().nullable(),
});

/**
 * Provides additional data about the resource that changed.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/resourcedata?view=graph-rest-1.0
 */
export const ChangeNotificationResourceData = z.object({
  '@odata.type': z.string(),
  '@odata.id': z.string(),
  id: z.string(),
});

/**
 * Represents the notification sent to the subscriber when data changes for which
 * a notification is requested.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/changenotification?view=graph-rest-1.0
 */
export const ChangeNotification = z.object({
  '@odata.type': z.string().optional(),
  changeType: SubscriptionChangeType,
  clientState: z.string().nullable(),
  resource: z.string(),
  resourceData: ChangeNotificationResourceData.nullish(),
  subscriptionExpirationDateTime: isoDatetimeToDate({ offset: true }),
  subscriptionId: z.string(),
  tenantId: z.string(),
});

/**
 * Represents a lifecycle notification sent when a subscription is about to expire,
 * is removed, or requires reauthorization.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/concepts/change-notifications-lifecycle-events?view=graph-rest-1.0
 */
export const LifecycleChangeNotification = z.object({
  subscriptionId: z.string(),
  subscriptionExpirationDateTime: isoDatetimeToDate({ offset: true }),
  tenantId: z.string().optional(),
  organizationId: z.string().optional(),
  clientState: z.string().nullable(),
  lifecycleEvent: LifecycleEventType,
});

/**
 * Represents a collection of change notifications sent to the subscriber.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/changenotificationcollection?view=graph-rest-1.0
 */
export const ChangeNotificationCollection = z.object({
  value: z.array(ChangeNotification),
  validationTokens: z.array(z.string()).optional(),
});

export type Subscription = z.infer<typeof Subscription>;
export type ChangeNotification = z.infer<typeof ChangeNotification>;
export type LifecycleChangeNotification = z.infer<typeof LifecycleChangeNotification>;
