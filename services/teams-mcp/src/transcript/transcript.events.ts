import z from 'zod/v4';
import { typeid } from '~/utils/zod';

// SECTION - Lifecycle events

const SubscriptionRequestedEvent = {
  type: 'unique.teams-mcp.transcript.lifecycle-notification.subscription-requested',
  schema: z.object({ userProfileId: typeid('user_profile') }),
} as const;

const SubscriptionRemovedEvent = {
  type: 'unique.teams-mcp.transcript.lifecycle-notification.subscription-removed',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

const MissedEvent = {
  type: 'unique.teams-mcp.transcript.lifecycle-notification.missed',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

const ReauthorizationRequiredEvent = {
  type: 'unique.teams-mcp.transcript.lifecycle-notification.reauthorization-required',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

export const lifecycle = {
  SubscriptionRequestedEvent,
  SubscriptionRemovedEvent,
  MissedEvent,
  ReauthorizationRequiredEvent,
} as const;

// !SECTION - Lifecycle events

// SECTION - Change events

const CreatedEvent = {
  type: 'unique.teams-mcp.transcript.change-notification.created',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

const UpdatedEvent = {
  type: 'unique.teams-mcp.transcript.change-notification.updated',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

const DeletedEvent = {
  type: 'unique.teams-mcp.transcript.change-notification.deleted',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

/**
 * On-demand ingest of a specific meeting transcript, requested via the `ingest_meeting` MCP tool.
 *
 * Unlike {@link CreatedEvent} (organizer push subscription), this is self-contained: it carries the
 * caller's `userProfileId` so the consumer can re-authenticate and resolve the meeting via `/me/...`
 * routes (the caller may be an invited attendee, not the organizer). No subscription is involved.
 *
 * Its `...change-notification.ingest-requested` type matches the existing change-notifications
 * queue routingKey wildcard, so no AMQP topology change is required.
 */
const IngestRequestedEvent = {
  type: 'unique.teams-mcp.transcript.change-notification.ingest-requested',
  schema: z.object({
    userProfileId: typeid('user_profile'), // caller; consumer re-auths and uses /me routes
    meetingId: z.string(),
    transcriptId: z.string(),
  }),
} as const;

export const change = {
  CreatedEvent,
  UpdatedEvent,
  DeletedEvent,
  IngestRequestedEvent,
} as const;

// !SECTION - Change events
