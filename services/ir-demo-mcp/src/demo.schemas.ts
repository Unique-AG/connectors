import { z } from 'zod';

const OptionalStringSchema = z.string().nullable().optional();
const OptionalNumberSchema = z.number().nullable().optional();
const DateFilterSchema = z.iso.date();

const BaseRecordSchema = z
  .object({
    id: z.string(),
    relationshipId: z.string().nullable(),
  })
  .passthrough();

export const RelationshipSchema = BaseRecordSchema.extend({
  relationshipType: z.enum(['investor', 'prospect']),
  name: z.string(),
  kind: z.enum(['existing', 'prospect']),
  investorId: OptionalStringSchema,
  prospectId: OptionalStringSchema,
  lpName: OptionalStringSchema,
  institution: OptionalStringSchema,
  lpType: OptionalStringSchema,
  fundType: OptionalStringSchema,
  relationshipStatus: OptionalStringSchema,
  pipelineStage: OptionalStringSchema,
  priorityTier: OptionalStringSchema,
  aumUsdBn: z.union([z.number(), z.string()]).nullable().optional(),
  probabilityPct: OptionalNumberSchema,
  targetCommitmentUsdMm: OptionalNumberSchema,
  weightedCommitmentUsdMm: OptionalNumberSchema,
}).passthrough();

export const CoverageAssignmentSchema = BaseRecordSchema.extend({
  coverageRole: z.string(),
  ownerName: z.string(),
  team: OptionalStringSchema,
  assignedDate: OptionalStringSchema,
}).passthrough();

export const ContactSchema = BaseRecordSchema.extend({
  contactId: OptionalStringSchema,
  name: z.string(),
  title: OptionalStringSchema,
  email: OptionalStringSchema,
  phone: OptionalStringSchema,
  roleType: OptionalStringSchema,
  primaryContact: OptionalStringSchema,
}).passthrough();

export const SubscriptionSchema = BaseRecordSchema.extend({
  fund: z.string(),
  initialSubscriptionDate: OptionalStringSchema,
  initialSubscriptionUsdMm: OptionalNumberSchema,
  currentNavUsdMm: OptionalNumberSchema,
  cumulativeNetReturnPct: OptionalNumberSchema,
  annualizedNetReturnPct: OptionalNumberSchema,
  highWaterMarkStatus: OptionalStringSchema,
  redemptionFrequency: OptionalStringSchema,
  redemptionNoticeDays: OptionalStringSchema,
}).passthrough();

export const DiligenceSchema = BaseRecordSchema.extend({
  type: z.string(),
  status: z.string(),
  targetDate: z.string().nullable(),
  ddqType: OptionalStringSchema,
  ddqStatus: OptionalStringSchema,
  sentDate: OptionalStringSchema,
  dueDate: OptionalStringSchema,
  targetCompletionDate: OptionalStringSchema,
  completedDate: OptionalStringSchema,
  lastCompletedDate: OptionalStringSchema,
  keyFocusAreas: OptionalStringSchema,
  notes: OptionalStringSchema,
}).passthrough();

export const TaskSchema = BaseRecordSchema.extend({
  taskId: OptionalStringSchema,
  description: z.string(),
  owner: z.string(),
  dueDate: OptionalStringSchema,
  priority: OptionalStringSchema,
  status: z.string(),
  notes: OptionalStringSchema,
}).passthrough();

export const ActivitySchema = BaseRecordSchema.extend({
  activityId: OptionalStringSchema,
  date: z.string(),
  type: z.string(),
  owner: z.string(),
  contactName: OptionalStringSchema,
  subject: OptionalStringSchema,
  notes: OptionalStringSchema,
  nextSteps: OptionalStringSchema,
}).passthrough();

export const OutlookTaskSchema = BaseRecordSchema.extend({
  taskId: z.string().optional(),
  subject: z.string(),
  body: z.string().optional(),
  dueDate: z.string().optional(),
  importance: z.string().optional(),
  status: z.string(),
  categories: z.array(z.string()).optional(),
}).passthrough();

export const CalendarEventSchema = BaseRecordSchema.extend({
  date: z.string(),
  time: z.string(),
  type: z.string(),
  kind: z.string(),
  owner: z.string(),
  attendees: z.union([z.string(), z.array(z.string())]),
  purpose: z.string(),
  status: z.string(),
  relatedItem: OptionalStringSchema,
}).passthrough();

export const MessageSchema = BaseRecordSchema.extend({
  sender: z.string(),
  recipients: z.array(z.string()),
  from: z.string(),
  to: z.array(z.string()),
  cc: z.array(z.string()).optional(),
  subject: z.string(),
  date: z.string(),
  body: z.string(),
}).passthrough();

export const RelationshipListInputSchema = z.object({
  relationshipId: z.string().min(1).optional().describe('Exact relationship ID.'),
  relationshipType: z
    .enum(['investor', 'prospect'])
    .optional()
    .describe('Investor maps to existing relationships; prospect maps to pipeline prospects.'),
  query: z.string().min(1).optional().describe('Case-insensitive relationship name search.'),
  relationshipStatus: z.string().min(1).optional(),
  pipelineStage: z.string().min(1).optional(),
  priority: z.string().min(1).optional().describe('Exact priority tier.'),
});

export const RelatedListInputSchema = z.object({
  relationshipId: z.string().min(1).optional(),
});

export const CoverageListInputSchema = RelatedListInputSchema.extend({
  owner: z.string().min(1).optional(),
  role: z.string().min(1).optional(),
  query: z.string().min(1).optional().describe('Searches owner, role, and team.'),
});

export const ContactListInputSchema = RelatedListInputSchema.extend({
  roleType: z.string().min(1).optional(),
  primaryContact: z.boolean().optional(),
  query: z.string().min(1).optional().describe('Searches contact name, title, email, and phone.'),
});

export const SubscriptionListInputSchema = RelatedListInputSchema.extend({
  fund: z.string().min(1).optional(),
  query: z.string().min(1).optional().describe('Searches fund and subscription status fields.'),
});

export const DiligenceListInputSchema = RelatedListInputSchema.extend({
  status: z.string().min(1).optional(),
  type: z.string().min(1).optional(),
  dueFrom: DateFilterSchema.optional(),
  dueTo: DateFilterSchema.optional(),
  query: z
    .string()
    .min(1)
    .optional()
    .describe('Searches diligence type, status, focus areas, and notes.'),
});

export const TaskListInputSchema = RelatedListInputSchema.extend({
  owner: z.string().min(1).optional(),
  status: z.string().min(1).optional(),
  priority: z.string().min(1).optional(),
  dueFrom: DateFilterSchema.optional(),
  dueTo: DateFilterSchema.optional(),
  query: z.string().min(1).optional().describe('Searches task description and notes.'),
});

export const ActivityListInputSchema = RelatedListInputSchema.extend({
  owner: z.string().min(1).optional(),
  type: z.string().min(1).optional(),
  dateFrom: DateFilterSchema.optional(),
  dateTo: DateFilterSchema.optional(),
  query: z
    .string()
    .min(1)
    .optional()
    .describe('Searches activity type, contact, subject, notes, and next steps.'),
});

export const OutlookTaskListInputSchema = z.object({
  status: z.string().min(1).optional(),
  importance: z.string().min(1).optional(),
  dueFrom: DateFilterSchema.optional(),
  dueTo: DateFilterSchema.optional(),
  query: z.string().min(1).optional().describe('Searches task subject, body, and categories.'),
});

export const CalendarListInputSchema = RelatedListInputSchema.extend({
  owner: z.string().min(1).optional(),
  type: z.string().min(1).optional(),
  kind: z.string().min(1).optional(),
  status: z.string().min(1).optional(),
  dateFrom: DateFilterSchema.optional(),
  dateTo: DateFilterSchema.optional(),
  query: z
    .string()
    .min(1)
    .optional()
    .describe('Searches event type, attendees, purpose, status, and related item.'),
});

export const MessageListInputSchema = RelatedListInputSchema.extend({
  sender: z.string().min(1).optional(),
  recipient: z.string().min(1).optional().describe('Matches To or Cc recipients.'),
  dateFrom: DateFilterSchema.optional(),
  dateTo: DateFilterSchema.optional(),
  query: z.string().min(1).optional().describe('Searches sender, recipients, subject, and body.'),
});

export const GetInputSchema = z.object({
  id: z.string().min(1),
});

export const RecordMeetingBriefInputSchema = z.object({
  eventId: z.string().min(1),
  meetingBriefPath: z.string().startsWith('/'),
});

export const RecordOutlookTaskArtifactInputSchema = z.object({
  taskId: z.string().min(1),
  artifactPath: z.string().startsWith('/'),
});

export const RelationshipListOutputSchema = z.object({
  items: z.array(RelationshipSchema),
  total: z.number().int().nonnegative(),
});
export const RelationshipOutputSchema = z.object({ item: RelationshipSchema });

export const CoverageListOutputSchema = z.object({
  items: z.array(CoverageAssignmentSchema),
  total: z.number().int().nonnegative(),
});
export const ContactListOutputSchema = z.object({
  items: z.array(ContactSchema),
  total: z.number().int().nonnegative(),
});
export const SubscriptionListOutputSchema = z.object({
  items: z.array(SubscriptionSchema),
  total: z.number().int().nonnegative(),
});
export const DiligenceListOutputSchema = z.object({
  items: z.array(DiligenceSchema),
  total: z.number().int().nonnegative(),
});
export const TaskListOutputSchema = z.object({
  items: z.array(TaskSchema),
  total: z.number().int().nonnegative(),
});
export const ActivityListOutputSchema = z.object({
  items: z.array(ActivitySchema),
  total: z.number().int().nonnegative(),
});
export const OutlookTaskListOutputSchema = z.object({
  items: z.array(OutlookTaskSchema),
  total: z.number().int().nonnegative(),
});
export const OutlookTaskOutputSchema = z.object({ item: OutlookTaskSchema });
export const CalendarListOutputSchema = z.object({
  items: z.array(CalendarEventSchema),
  total: z.number().int().nonnegative(),
});
export const CalendarOutputSchema = z.object({ item: CalendarEventSchema });
export const MessageListOutputSchema = z.object({
  items: z.array(MessageSchema),
  total: z.number().int().nonnegative(),
});
export const MessageOutputSchema = z.object({ item: MessageSchema });
