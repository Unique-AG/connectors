import { createZodDto } from 'nestjs-zod';
import { type Join, type Split } from 'type-fest';
import z from 'zod/v4';
import { isoDatetimeToDate, redacted, stringToURL } from '~/utils/zod';
import { change, lifecycle } from './transcript.events';

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
    organizationId: z.string(), // NOTE: this would be the tenantId, but API returns it as organizationId
    clientState: redacted(z.string()).nullable(),
    resourceData: ChangeNotificationResourceData.nullish(),
    encryptedContent: ChangeNotificationEncryptedContent.nullish(),
    lifecycleEvent: LifecycleEventType,
  })
  .transform((values) => ({
    ...values,
    tenantId: values.organizationId,
  }));
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
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0&tabs=http#http-request call transcript resource}.
 */
export const TranscriptResourceSchema = z.string().transform((resource, ctx) => {
  // NOTE: resource is in the format of "users(id)/onlineMeetings(id)/transcripts(id)"
  const [users, onlineMeetings, transcripts] = resource.split('/');
  const usersIdRegex = new RegExp(/^users\('(.+)'\)$/);
  const userId = usersIdRegex.exec(users ?? '')?.[1];
  const onlineMeetingIdRegex = new RegExp(/^onlineMeetings\('(.+)'\)$/);
  const meetingId = onlineMeetingIdRegex.exec(onlineMeetings ?? '')?.[1];
  const transcriptIdRegex = new RegExp(/^transcripts\('(.+)'\)$/);
  const transcriptId = transcriptIdRegex.exec(transcripts ?? '')?.[1];

  if (!userId || !meetingId || !transcriptId) {
    ctx.addIssue({
      input: resource,
      code: 'invalid_format',
      format: 'regex',
      pattern: 'users(id)/onlineMeetings(id)/transcripts(id)',
      message: 'Resource does not contain online expected ids',
    });
    return z.NEVER;
  }

  return { userId, meetingId, transcriptId };
});

export const TranscriptVttMetadataSchema = z
  .base64()
  .transform((b) => Buffer.from(b, 'base64').toString())
  .transform((vtt, ctx) => {
    const languages = new Map<string, number>();
    const languagePattern = /"spokenLanguage":"(.*?)"/g;
    let match: RegExpExecArray | null;

    // biome-ignore lint/suspicious/noAssignInExpressions: this is a common pattern for exec
    while ((match = languagePattern.exec(vtt)) !== null) {
      const extractedLanguage = match[1];
      if (!extractedLanguage) {
        ctx.addIssue({
          code: 'invalid_format',
          format: 'regex',
          path: ['languagePattern'],
          pattern: languagePattern.source,
          message: 'Spoken Language group is expected to have a group value',
        });
        continue;
      }
      const [locale, region] = extractedLanguage.split('-');
      if (!locale) {
        ctx.addIssue({
          code: 'invalid_format',
          format: 'iso-language',
          path: ['extractedLanguage'],
          message: 'The extracted language was expected to have at least the locale part',
        });
        continue;
      }
      const language = region ? `${locale}-${region.toUpperCase()}` : locale;

      const count = languages.get(language) ?? 0;
      languages.set(language, count + 1);
    }
    const entries = Array.from(languages.entries());
    const mostSpoken = entries.length > 0 ? entries.reduce((a, b) => (a[1] > b[1] ? a : b))[0] : '';

    if (ctx.issues.length > 0) return z.NEVER;

    return { mostSpoken, languages };
  });

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0&tabs=http#response-1 transcript}.
 */
export const Transcript = z.object({
  id: z.string(),
  meetingId: z.string(),
  callId: z.string(),
  contentCorrelationId: z.string(),
  transcriptContentUrl: stringToURL(),
  createdDateTime: isoDatetimeToDate({ offset: true }),
  endDateTime: isoDatetimeToDate({ offset: true }),
  meetingOrganizer: z.object({
    application: z.string().nullable(),
    device: z.string().nullable(),
    user: z.object({
      userIdentityType: z.string(),
      tenantId: z.string(),
      id: z.string(),
      displayName: z.string().nullable(),
    }),
  }),
});
export type Transcript = z.infer<typeof Transcript>;

export const TranscriptCollection = Collection(Transcript);

const extractThreadId = (url: URL): string | null => {
  const match = url.pathname.match(/\/meetup-join\/([^/]+)/);
  const threadId = match?.[1];
  if (!threadId) {
    return null;
  }
  return decodeURIComponent(threadId);
};

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/resources/onlinemeeting?view=graph-rest-1.0#properties online meeting properties}.
 */
export const Meeting = z
  .object({
    id: z.string(),
    recordAutomatically: z.boolean().nullish(),
    allowTranscription: z.boolean().nullish(),
    allowRecording: z.boolean().nullish(),
    subject: z.string().nullish(),
    startDateTime: isoDatetimeToDate({ offset: true }),
    endDateTime: isoDatetimeToDate({ offset: true }),
    joinWebUrl: stringToURL(),
    participants: z.object({
      attendees: z.array(
        z.object({
          upn: z.string(),
          identity: z.object({
            user: z.object({
              id: z.string().nullish(),
              tenantId: z.string().nullish(),
              displayName: z.string().nullish(),
            }),
          }),
        }),
      ),
      organizer: z.object({
        upn: z.string(),
        identity: z.object({
          user: z.object({
            id: z.string(),
            tenantId: z.string(),
            displayName: z.string().nullish(),
          }),
        }),
      }),
    }),
  })
  .transform((m, ctx) => {
    const threadId = extractThreadId(m.joinWebUrl);
    if (!threadId) {
      ctx.addIssue({
        code: 'custom',
        message: `Expected Teams meeting URL with threadId in path (e.g., /meetup-join/{threadId}/...), got: ${m.joinWebUrl.pathname}`,
      });
      return z.NEVER;
    }
    return { ...m, threadId };
  });
export type Meeting = z.infer<typeof Meeting>;

export const MeetingCollection = Collection(Meeting);

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0 calendar event}.
 *
 * Used to determine if a meeting is recurring by checking the `type` or `seriesMasterId` properties.
 */
export const CalendarEvent = z
  .object({
    id: z.string(),
    subject: z.string().nullish(),
    type: z.enum(['singleInstance', 'occurrence', 'exception', 'seriesMaster']),
    seriesMasterId: z.string().nullish(),
    onlineMeeting: z
      .object({
        joinUrl: stringToURL(),
      })
      .nullish(),
  })
  .transform((e) => ({
    ...e,
    threadId: e.onlineMeeting ? extractThreadId(e.onlineMeeting.joinUrl) : null,
  }));
export type CalendarEvent = z.infer<typeof CalendarEvent>;

export const CalendarEventCollection = Collection(CalendarEvent);

/**
 * See docs on {@link https://learn.microsoft.com/en-us/graph/api/resources/callrecording?view=graph-rest-1.0 call recording}.
 */
export const Recording = z.object({
  id: z.string(),
  meetingId: z.string(),
  callId: z.string(),
  contentCorrelationId: z.string(),
  recordingContentUrl: stringToURL(),
  createdDateTime: isoDatetimeToDate({ offset: true }),
  endDateTime: isoDatetimeToDate({ offset: true }),
  meetingOrganizer: z.object({
    application: z.string().nullable(),
    device: z.string().nullable(),
    user: z.object({
      userIdentityType: z.string(),
      tenantId: z.string(),
      id: z.string(),
      displayName: z.string().nullable(),
    }),
  }),
});
export type Recording = z.infer<typeof Recording>;

export const RecordingCollection = Collection(Recording);

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

export const SubscriptionRequestedEventDto = lifecycle.SubscriptionRequestedEvent.schema.safeExtend(
  {
    type: z.literal(lifecycle.SubscriptionRequestedEvent.type),
  },
);
export type SubscriptionRequestedEventDto = z.output<typeof SubscriptionRequestedEventDto>;

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
  SubscriptionRequestedEventDto,
  SubscriptionRemovedEventDto,
  MissedEventDto,
  ReauthorizationRequiredEventDto,
]);
export type LifecycleEventDto = z.output<typeof LifecycleEventDto>;

// !SECTION - Lifecycle Events

// SECTION - Change Events

export const CreatedEventDto = change.CreatedEvent.schema.safeExtend({
  type: z.literal(change.CreatedEvent.type),
});
export type CreatedEventDto = z.output<typeof CreatedEventDto>;

export const UpdatedEventDto = change.UpdatedEvent.schema.safeExtend({
  type: z.literal(change.UpdatedEvent.type),
});
export type UpdatedEventDto = z.output<typeof UpdatedEventDto>;

export const DeletedEventDto = change.DeletedEvent.schema.safeExtend({
  type: z.literal(change.DeletedEvent.type),
});
export type DeletedEventDto = z.output<typeof DeletedEventDto>;

export const ChangeEventDto = z.discriminatedUnion('type', [
  CreatedEventDto,
  UpdatedEventDto,
  DeletedEventDto,
]);
export type ChangeEventDto = z.output<typeof ChangeEventDto>;

// !SECTION - Change Events
