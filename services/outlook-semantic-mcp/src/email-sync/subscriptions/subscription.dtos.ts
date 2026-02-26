import { createZodDto } from 'nestjs-zod';
import { type Join, type Split } from 'type-fest';
import z from 'zod/v4';
import { isoDatetimeToDate, redacted, stringToURL } from '~/utils/zod';
import { lifecycle } from './subscription.events';
import { isString } from 'remeda';

// SECTION - Microsoft Graph types

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/paging?tabs=http paging lists}.
 */
export const Collection = <S extends z.core.$ZodType>(schema: S) =>
  z.object({
    '@odata.nextLink': z.string().optional(),
    value: z.array(schema),
    validationTokens: z.array(z.string()).optional(),
  });

/**
 * Lifecycle events are notifications that in the lifetime of a subscription, Microsoft Graph sends special kinds of notifications to help you minimize the risk of missing subscriptions and change notifications.
 *
 * Resource events are notifications that Microsoft Graph sends when a resource changes.
 *
 * See docs on {@link https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events?tabs=http change notifications lifecycle events}.
 */
export const NotificationType = z.enum(['resource', 'lifecycle']);
export type NotificationType = z.infer<typeof NotificationType>;

/**
 * Notifications payload with resource contains the encrypted content of the resource data.
 *
 * Notifications payload without resource does not contain the encrypted content of the resource data.
 *
 * See docs on {@link https://learn.microsoft.com/en-us/graph/teams-changenotifications-callrecording-and-calltranscript#notifications-with-resource-data notifications with resource data}
 * and {@link https://learn.microsoft.com/en-us/graph/change-notifications-with-resource-data rich notifications}.
 */
export const NotificationPayloadType = z.enum(['withResource', 'withoutResource']);
export type NotificationPayloadType = z.infer<typeof NotificationPayloadType>;

/**
 * The type of the lifecycle event.
 *
 * See docs on {@link https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events?tabs=http#structure-of-a-lifecycle-notification structure of a lifecycle notification}.
 */
export const LifecycleEventType = z.enum([
  'subscriptionRemoved',
  'missed',
  'reauthorizationRequired',
]);
export type LifecycleEventType = z.infer<typeof LifecycleEventType>;

/**
 * The change type of the resource subscribed to.
 */
export const NotificationChangeType = z.enum(['created', 'updated', 'deleted']);
export type NotificationChangeType = z.infer<typeof NotificationChangeType>;
// REVIEW: could it happen that types combinations have a different order than the one we manually made here?
export const NotificationChangeTypeCombinations = z.enum([
  'created',
  'updated',
  'deleted',
  'created,updated',
  'created,deleted',
  'updated,deleted',
  'created,updated,deleted',
]);
export type NotificationChangeTypeCombinations = z.infer<typeof NotificationChangeTypeCombinations>;

export const MultipleNotificationChangeType = z.codec(
  NotificationChangeTypeCombinations,
  z.array(NotificationChangeType),
  {
    decode(value) {
      return value.split(',') as Split<NotificationChangeTypeCombinations, ','>;
    },
    encode(value) {
      return value.join(',') as Join<[NotificationChangeType], ','>;
    },
  },
);
export type MultipleNotificationChangeTypeInput = z.input<typeof MultipleNotificationChangeType>;
export type MultipleNotificationChangeTypeOutput = z.output<typeof MultipleNotificationChangeType>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/subscription-list?view=graph-rest-1.0&tabs=http#response-1 subscription list}.
 */
export const Subscription = z.object({
  id: z.string(),
  resource: z.string(),
  applicationId: z.string(),
  changeType: MultipleNotificationChangeType,
  clientState: redacted(z.string()).nullable(),
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
export type Subscription = z.infer<typeof Subscription>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/subscription-list?view=graph-rest-1.0&tabs=http#response-1 subscription list}.
 */
export const SubscriptionCollectionSchema = Collection(Subscription);
export class SubscriptionCollectionDto extends createZodDto(SubscriptionCollectionSchema) {}

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/teams-changenotifications-callrecording-and-calltranscript#notifications-without-resource-data notification without resource data}.
 */
export const ChangeNotificationResourceData = z.object({
  id: z.string(),
  '@odata.type': z.string(),
  '@odata.id': z.string(),
});
export type ChangeNotificationResourceData = z.infer<typeof ChangeNotificationResourceData>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/teams-changenotifications-callrecording-and-calltranscript#notifications-with-resource-data notifications with resource data}
 * and {@link https://learn.microsoft.com/en-us/graph/change-notifications-with-resource-data rich notifications}.
 */
export const ChangeNotificationEncryptedContent = z.object({
  data: z.string(),
  dataSignature: z.string(),
  dataKey: z.string(),
  encryptionCertificateId: z.string(),
  encryptionCertificateThumbprint: z.string(),
});
export type ChangeNotificationEncryptedContent = z.infer<typeof ChangeNotificationEncryptedContent>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/resources/changenotification?view=graph-rest-1.0 change notifications}.
 */
export const ChangeNotification = z.object({
  '@odata.type': z.string().optional(),
  changeType: NotificationChangeType,
  clientState: redacted(z.string()).nullable(),
  resource: z.string(),
  resourceData: ChangeNotificationResourceData.nullish(),
  encryptedContent: ChangeNotificationEncryptedContent.nullish(),
  subscriptionExpirationDateTime: isoDatetimeToDate({ offset: true }),
  subscriptionId: z.string(),
  tenantId: z.string(),
});
export type ChangeNotification = z.infer<typeof ChangeNotification>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/resources/changenotificationcollection?view=graph-rest-1.0 change notifications collection}.
 */
export const ChangeNotificationCollection = Collection(ChangeNotification);
export class ChangeNotificationCollectionDto extends createZodDto(ChangeNotificationCollection) {}

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events?tabs=http#structure-of-a-lifecycle-notification structure of a lifecycle notification}.
 */
export const LifecycleChangeNotification = z
  .object({
    subscriptionId: z.string(),
    subscriptionExpirationDateTime: isoDatetimeToDate({ offset: true }),
    tenantId: z.string().optional(),
    organizationId: z.string().optional(), // NOTE: this would be the tenantId, but API returns it as organizationId
    clientState: redacted(z.string()).nullable(),
    resourceData: ChangeNotificationResourceData.nullish(),
    encryptedContent: ChangeNotificationEncryptedContent.nullish(),
    lifecycleEvent: LifecycleEventType,
  })
  .transform(({ organizationId, tenantId, ...values }) => ({
    ...values,
    tenantId: tenantId ?? organizationId,
  }))
  .refine(({ tenantId }) => isString(tenantId) && tenantId.length > 0, {
    message: 'tenantId must be a string',
    path: ['tenantId'],
  });

export type LifecycleChangeNotification = z.infer<typeof LifecycleChangeNotification>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events?tabs=http#structure-of-a-lifecycle-notification structure of a lifecycle notification}.
 */
export const LifecycleChangeNotificationCollectionSchema = Collection(LifecycleChangeNotification);
export class LifecycleChangeNotificationCollectionDto extends createZodDto(
  LifecycleChangeNotificationCollectionSchema,
) {}

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0&tabs=http create subscription}.
 */
export const CreateSubscriptionRequestSchema = z.object({
  changeType: MultipleNotificationChangeType,
  notificationUrl: stringToURL(),
  lifecycleNotificationUrl: stringToURL().optional(),
  includeResourceData: z.boolean().optional(),
  encryptionCertificate: z.string().optional(),
  encryptionCertificateId: z.string().optional(),
  clientState: redacted(z.string()),
  resource: z.string(),
  expirationDateTime: isoDatetimeToDate({ offset: true }),
});
export type CreateSubscriptionRequestInput = z.input<typeof CreateSubscriptionRequestSchema>;
export type CreateSubscriptionRequestOutput = z.output<typeof CreateSubscriptionRequestSchema>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/subscription-update?view=graph-rest-1.0&tabs=http update subscription}.
 */
export const UpdateSubscriptionRequestSchema = z.object({
  expirationDateTime: isoDatetimeToDate({ offset: true }),
});
export type UpdateSubscriptionRequestInput = z.input<typeof UpdateSubscriptionRequestSchema>;
export type UpdateSubscriptionRequestOutput = z.output<typeof UpdateSubscriptionRequestSchema>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/json-batching#explanation-of-a-batch-request-format batch request}.
 */
export const BatchRequestPayload = z.object({
  id: z.string(),
  method: z.enum(['GET', 'POST', 'PATCH', 'DELETE']),
  url: z.string(),
  headers: z.record(z.string(), z.string()).optional(),
  body: z.unknown().optional(),
});
export type BatchRequestPayload = z.infer<typeof BatchRequestPayload>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/json-batching#explanation-of-a-batch-request-format batch request}.
 */
export const BatchRequest = z.object({
  requests: z.array(BatchRequestPayload),
});
export type BatchRequest = z.infer<typeof BatchRequest>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/json-batching#explanation-of-a-batch-request-format batch request}.
 */
export const BatchResponsePayload = z.object({
  id: z.string(),
  status: z.number(),
  headers: z.record(z.string(), z.string()).optional(),
  body: z.unknown().nullish(),
});
export type BatchResponsePayload = z.infer<typeof BatchResponsePayload>;

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/json-batching#explanation-of-a-batch-request-format batch request}.
 */
export const BatchResponse = z.object({
  responses: z.array(BatchResponsePayload),
});
export type BatchResponse = z.infer<typeof BatchResponse>;

// !SECTION - Microsoft Graph types

// SECTION - Lifecycle Events

export const SubscriptionCreatedEventDto = lifecycle.SubscriptionCreatedEvent.schema.safeExtend({
  type: z.literal(lifecycle.SubscriptionCreatedEvent.type),
});
// unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-created

export const SubscriptionRemovedEventDto = lifecycle.SubscriptionRemovedEvent.schema.safeExtend({
  type: z.literal(lifecycle.SubscriptionRemovedEvent.type),
});
export type SubscriptionRemovedEventDto = z.output<typeof SubscriptionRemovedEventDto>;

export const MissedEventDto = lifecycle.MissedEvent.schema.safeExtend({
  type: z.literal(lifecycle.MissedEvent.type),
});
export type MissedEventDto = z.output<typeof MissedEventDto>;

export const ReauthorizationRequiredEventDto =
  lifecycle.ReauthorizationRequiredEvent.schema.safeExtend({
    type: z.literal(lifecycle.ReauthorizationRequiredEvent.type),
  });
export type ReauthorizationRequiredEventDto = z.output<typeof ReauthorizationRequiredEventDto>;

export const LifecycleEventDto = z.discriminatedUnion('type', [
  SubscriptionRemovedEventDto,
  MissedEventDto,
  ReauthorizationRequiredEventDto,
  SubscriptionCreatedEventDto,
]);
export type LifecycleEventDto = z.output<typeof LifecycleEventDto>;

// !SECTION - Lifecycle Events
