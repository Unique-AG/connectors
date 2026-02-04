import z from 'zod/v4';
import { typeid } from '~/utils/zod';

// SECTION - Lifecycle events

const SubscriptionRequestedEvent = {
  type: 'unique.outlook-fat-mcp.transcript.lifecycle-notification.subscription-requested',
  schema: z.object({ userProfileId: typeid('user_profile') }),
} as const;

const SubscriptionRemovedEvent = {
  type: 'unique.outlook-fat-mcp.transcript.lifecycle-notification.subscription-removed',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

const MissedEvent = {
  type: 'unique.outlook-fat-mcp.transcript.lifecycle-notification.missed',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

const ReauthorizationRequiredEvent = {
  type: 'unique.outlook-fat-mcp.transcript.lifecycle-notification.reauthorization-required',
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
  type: 'unique.outlook-fat-mcp.transcript.change-notification.created',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

const UpdatedEvent = {
  type: 'unique.outlook-fat-mcp.transcript.change-notification.updated',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

const DeletedEvent = {
  type: 'unique.outlook-fat-mcp.transcript.change-notification.deleted',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

export const change = {
  CreatedEvent,
  UpdatedEvent,
  DeletedEvent,
} as const;

// !SECTION - Change events
