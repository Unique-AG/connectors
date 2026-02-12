import z from 'zod/v4';

// SECTION - Lifecycle events
const SubscriptionCreatedEvent = {
  type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-created',
  schema: z.object({ subscriptionId: z.string() }),
};

const SubscriptionRemovedEvent = {
  type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-removed',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

const MissedEvent = {
  type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.missed',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

const ReauthorizationRequiredEvent = {
  type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.reauthorization-required',
  schema: z.object({ subscriptionId: z.string() }),
} as const;

export const lifecycle = {
  SubscriptionRemovedEvent,
  SubscriptionCreatedEvent,
  MissedEvent,
  ReauthorizationRequiredEvent,
} as const;

// !SECTION - Lifecycle events

// SECTION - Change events

const CreatedEvent = {
  type: 'unique.outlook-semantic-mcp.mail.change-notification.created',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

const UpdatedEvent = {
  type: 'unique.outlook-semantic-mcp.mail.change-notification.updated',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

const DeletedEvent = {
  type: 'unique.outlook-semantic-mcp.mail.change-notification.deleted',
  schema: z.object({ subscriptionId: z.string(), resource: z.string() }),
} as const;

export const change = {
  CreatedEvent,
  UpdatedEvent,
  DeletedEvent,
} as const;

// !SECTION - Change events
