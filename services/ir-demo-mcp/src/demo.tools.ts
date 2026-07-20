import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { z } from 'zod';
import { DemoRepository } from './data/demo.repository';
import {
  compareByDate,
  matchesDateRange,
  matchesListValue,
  matchesQuery,
  matchesValue,
  normalizeDiligenceRecord,
  toPublicMessage,
  toPublicRecord,
  toPublicRelationship,
} from './demo.filters';
import {
  ActivityListInputSchema,
  ActivityListOutputSchema,
  ActivitySchema,
  CalendarEventSchema,
  CalendarListInputSchema,
  CalendarListOutputSchema,
  CalendarOutputSchema,
  ContactListInputSchema,
  ContactListOutputSchema,
  ContactSchema,
  CoverageAssignmentSchema,
  CoverageListInputSchema,
  CoverageListOutputSchema,
  DiligenceListInputSchema,
  DiligenceListOutputSchema,
  DiligenceSchema,
  GetInputSchema,
  MessageListInputSchema,
  MessageListOutputSchema,
  MessageOutputSchema,
  MessageSchema,
  RelationshipListInputSchema,
  RelationshipListOutputSchema,
  RelationshipOutputSchema,
  RelationshipSchema,
  SubscriptionListInputSchema,
  SubscriptionListOutputSchema,
  SubscriptionSchema,
  TaskListInputSchema,
  TaskListOutputSchema,
  TaskSchema,
} from './demo.schemas';

const READ_ONLY_ANNOTATIONS = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
} as const;

@Injectable()
export class DemoTools {
  public constructor(private readonly repository: DemoRepository) {}

  @Tool({
    name: 'crm_list_relationships',
    title: 'List CRM Relationships',
    description:
      'List investor and prospect relationships, optionally filtered by identity, name, status, pipeline stage, or priority.',
    parameters: RelationshipListInputSchema,
    outputSchema: RelationshipListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listRelationships(
    input: z.infer<typeof RelationshipListInputSchema>,
    _context: Context,
  ): z.infer<typeof RelationshipListOutputSchema> {
    const items = this.repository
      .list('relationships')
      .filter((record) => input.relationshipId === undefined || record.id === input.relationshipId)
      .filter(
        (record) =>
          input.relationshipType === undefined ||
          record.data.kind === (input.relationshipType === 'investor' ? 'existing' : 'prospect'),
      )
      .filter((record) => matchesQuery(record, ['name', 'lpName', 'institution'], input.query))
      .filter((record) => matchesValue(record, 'relationshipStatus', input.relationshipStatus))
      .filter((record) => matchesValue(record, 'pipelineStage', input.pipelineStage))
      .filter((record) => matchesValue(record, 'priorityTier', input.priority))
      .map((record) => RelationshipSchema.parse(toPublicRelationship(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'crm_get_relationship',
    title: 'Get CRM Relationship',
    description: 'Get one investor or prospect relationship by ID.',
    parameters: GetInputSchema,
    outputSchema: RelationshipOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public getRelationship(
    input: z.infer<typeof GetInputSchema>,
    _context: Context,
  ): z.infer<typeof RelationshipOutputSchema> {
    const record = this.repository.get('relationships', input.id);
    if (record === undefined) {
      throw new Error(`Relationship "${input.id}" was not found.`);
    }
    return { item: RelationshipSchema.parse(toPublicRelationship(record)) };
  }

  @Tool({
    name: 'crm_list_contacts',
    title: 'List CRM Contacts',
    description:
      'List relationship contacts, optionally filtered by relationship, role, primary-contact status, or text.',
    parameters: ContactListInputSchema,
    outputSchema: ContactListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listContacts(
    input: z.infer<typeof ContactListInputSchema>,
    _context: Context,
  ): z.infer<typeof ContactListOutputSchema> {
    const items = this.repository
      .list('contacts', input.relationshipId)
      .filter((record) => matchesValue(record, 'roleType', input.roleType))
      .filter((record) =>
        matchesValue(
          record,
          'primaryContact',
          input.primaryContact === undefined ? undefined : input.primaryContact ? 'Yes' : 'No',
        ),
      )
      .filter((record) => matchesQuery(record, ['name', 'title', 'email', 'phone'], input.query))
      .map((record) => ContactSchema.parse(toPublicRecord(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'crm_list_coverage_assignments',
    title: 'List CRM Coverage Assignments',
    description:
      'List relationship coverage assignments, optionally filtered by relationship, owner, role, or text.',
    parameters: CoverageListInputSchema,
    outputSchema: CoverageListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listCoverageAssignments(
    input: z.infer<typeof CoverageListInputSchema>,
    _context: Context,
  ): z.infer<typeof CoverageListOutputSchema> {
    const items = this.repository
      .list('coverageAssignments', input.relationshipId)
      .filter((record) => matchesValue(record, 'ownerName', input.owner))
      .filter((record) => matchesValue(record, 'coverageRole', input.role))
      .filter((record) => matchesQuery(record, ['ownerName', 'coverageRole', 'team'], input.query))
      .map((record) => CoverageAssignmentSchema.parse(toPublicRecord(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'crm_list_subscriptions',
    title: 'List CRM Subscriptions',
    description:
      'List relationship fund subscriptions and their commitment, NAV, performance, and redemption details.',
    parameters: SubscriptionListInputSchema,
    outputSchema: SubscriptionListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listSubscriptions(
    input: z.infer<typeof SubscriptionListInputSchema>,
    _context: Context,
  ): z.infer<typeof SubscriptionListOutputSchema> {
    const items = this.repository
      .list('subscriptions', input.relationshipId)
      .filter((record) => matchesValue(record, 'fund', input.fund))
      .filter((record) =>
        matchesQuery(record, ['fund', 'highWaterMarkStatus', 'redemptionFrequency'], input.query),
      )
      .map((record) => SubscriptionSchema.parse(toPublicRecord(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'crm_list_diligence',
    title: 'List CRM Diligence',
    description:
      'List diligence and compliance items, optionally filtered by relationship, status, type, due-date range, or text.',
    parameters: DiligenceListInputSchema,
    outputSchema: DiligenceListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listDiligence(
    input: z.infer<typeof DiligenceListInputSchema>,
    _context: Context,
  ): z.infer<typeof DiligenceListOutputSchema> {
    const items = this.repository
      .list('diligence', input.relationshipId)
      .map(normalizeDiligenceRecord)
      .filter((record) => matchesValue(record, 'status', input.status))
      .filter((record) => matchesValue(record, 'type', input.type))
      .filter((record) => matchesDateRange(record, 'targetDate', input.dueFrom, input.dueTo))
      .filter((record) =>
        matchesQuery(
          record,
          ['type', 'status', 'ddqType', 'ddqStatus', 'keyFocusAreas', 'notes'],
          input.query,
        ),
      )
      .sort((left, right) => compareByDate(left, right, 'targetDate', 'ascending'))
      .map((record) => DiligenceSchema.parse(toPublicRecord(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'crm_list_tasks',
    title: 'List CRM Tasks',
    description:
      'List relationship tasks, optionally filtered by owner, status, priority, due-date range, or text.',
    parameters: TaskListInputSchema,
    outputSchema: TaskListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listTasks(
    input: z.infer<typeof TaskListInputSchema>,
    _context: Context,
  ): z.infer<typeof TaskListOutputSchema> {
    const items = this.repository
      .list('tasks', input.relationshipId)
      .filter((record) => matchesValue(record, 'owner', input.owner))
      .filter((record) => matchesValue(record, 'status', input.status))
      .filter((record) => matchesValue(record, 'priority', input.priority))
      .filter((record) => matchesDateRange(record, 'dueDate', input.dueFrom, input.dueTo))
      .filter((record) => matchesQuery(record, ['description', 'notes'], input.query))
      .sort((left, right) => compareByDate(left, right, 'dueDate', 'ascending'))
      .map((record) => TaskSchema.parse(toPublicRecord(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'crm_list_activities',
    title: 'List CRM Activities',
    description:
      'List relationship activities newest first, optionally filtered by owner, type, date range, or text.',
    parameters: ActivityListInputSchema,
    outputSchema: ActivityListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listActivities(
    input: z.infer<typeof ActivityListInputSchema>,
    _context: Context,
  ): z.infer<typeof ActivityListOutputSchema> {
    const items = this.repository
      .list('activities', input.relationshipId)
      .filter((record) => matchesValue(record, 'owner', input.owner))
      .filter((record) => matchesValue(record, 'type', input.type))
      .filter((record) => matchesDateRange(record, 'date', input.dateFrom, input.dateTo))
      .filter((record) =>
        matchesQuery(record, ['type', 'contactName', 'subject', 'notes', 'nextSteps'], input.query),
      )
      .sort((left, right) => compareByDate(left, right, 'date', 'descending'))
      .map((record) => ActivitySchema.parse(toPublicRecord(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'outlook_list_calendar_events',
    title: 'List Outlook Calendar Events',
    description:
      'List calendar events earliest first, optionally filtered by relationship, date range, owner, type, kind, status, or text.',
    parameters: CalendarListInputSchema,
    outputSchema: CalendarListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listCalendarEvents(
    input: z.infer<typeof CalendarListInputSchema>,
    _context: Context,
  ): z.infer<typeof CalendarListOutputSchema> {
    const items = this.repository
      .list('calendarEvents', input.relationshipId)
      .filter((record) => matchesValue(record, 'owner', input.owner))
      .filter((record) => matchesValue(record, 'type', input.type))
      .filter((record) => matchesValue(record, 'kind', input.kind))
      .filter((record) => matchesValue(record, 'status', input.status))
      .filter((record) => matchesDateRange(record, 'date', input.dateFrom, input.dateTo))
      .filter((record) =>
        matchesQuery(
          record,
          ['type', 'attendees', 'purpose', 'status', 'relatedItem'],
          input.query,
        ),
      )
      .sort((left, right) => compareByDate(left, right, 'date', 'ascending'))
      .map((record) => CalendarEventSchema.parse(toPublicRecord(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'outlook_get_calendar_event',
    title: 'Get Outlook Calendar Event',
    description: 'Get one calendar event by ID.',
    parameters: GetInputSchema,
    outputSchema: CalendarOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public getCalendarEvent(
    input: z.infer<typeof GetInputSchema>,
    _context: Context,
  ): z.infer<typeof CalendarOutputSchema> {
    const record = this.repository.get('calendarEvents', input.id);
    if (record === undefined) {
      throw new Error(`Calendar event "${input.id}" was not found.`);
    }
    return { item: CalendarEventSchema.parse(toPublicRecord(record)) };
  }

  @Tool({
    name: 'outlook_list_messages',
    title: 'List Outlook Messages',
    description:
      'List email messages newest first, optionally filtered by relationship, date range, sender, recipient, or text.',
    parameters: MessageListInputSchema,
    outputSchema: MessageListOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public listMessages(
    input: z.infer<typeof MessageListInputSchema>,
    _context: Context,
  ): z.infer<typeof MessageListOutputSchema> {
    const items = this.repository
      .list('messages', input.relationshipId)
      .filter((record) => matchesValue(record, 'from', input.sender))
      .filter((record) => matchesListValue(record, ['to', 'cc'], input.recipient))
      .filter((record) => matchesDateRange(record, 'date', input.dateFrom, input.dateTo))
      .filter((record) =>
        matchesQuery(record, ['from', 'to', 'cc', 'subject', 'body'], input.query),
      )
      .sort((left, right) => compareByDate(left, right, 'date', 'descending'))
      .map((record) => MessageSchema.parse(toPublicMessage(record)));
    return { items, total: items.length };
  }

  @Tool({
    name: 'outlook_get_message',
    title: 'Get Outlook Message',
    description: 'Get one email message by ID.',
    parameters: GetInputSchema,
    outputSchema: MessageOutputSchema,
    annotations: READ_ONLY_ANNOTATIONS,
  })
  public getMessage(
    input: z.infer<typeof GetInputSchema>,
    _context: Context,
  ): z.infer<typeof MessageOutputSchema> {
    const record = this.repository.get('messages', input.id);
    if (record === undefined) {
      throw new Error(`Message "${input.id}" was not found.`);
    }
    return { item: MessageSchema.parse(toPublicMessage(record)) };
  }
}
