import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { z } from 'zod';
import { DemoRepository } from './data/demo.repository';
import { DemoRecord } from './data/demo-record';

const EmptyInputSchema = z.object({});
const ListOutputSchema = z.object({
  items: z.array(z.record(z.string(), z.unknown())),
});
const CompleteOutputSchema = z.object({
  item: z.record(z.string(), z.unknown()),
  completed: z.boolean(),
});
const ActivityInputSchema = z.object({
  period: z.enum(['today', 'week']).optional(),
});
const CompleteInputSchema = z.object({
  id: z.string().min(1),
});

const toPublicRecord = (record: DemoRecord): Record<string, unknown> => ({
  ...record.data,
  id: record.id,
  relationshipId: record.relationshipId,
});

const recordDate = (record: DemoRecord): number => {
  const candidates = ['date', 'activityDate', 'interactionDate', 'startDate', 'timestamp'];
  for (const key of candidates) {
    const value = record.data[key];
    if (typeof value === 'string') {
      const timestamp = Date.parse(value);
      if (!Number.isNaN(timestamp)) {
        return timestamp;
      }
    }
  }
  return 0;
};

@Injectable()
export class DemoTools {
  public constructor(private readonly repository: DemoRepository) {}

  @Tool({
    name: 'crm_list_investors',
    title: 'List Investors',
    description: 'List existing investors and prospects with their current relationship status.',
    parameters: EmptyInputSchema,
    outputSchema: ListOutputSchema,
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  })
  public listInvestors(
    _input: z.infer<typeof EmptyInputSchema>,
    _context: Context,
  ): z.infer<typeof ListOutputSchema> {
    const items = this.repository.list('relationships').map(toPublicRecord);
    return { items };
  }

  @Tool({
    name: 'crm_list_recent_activity',
    title: 'List Recent Activity',
    description: 'List investor-relations activity and open follow-ups for the demo snapshot.',
    parameters: ActivityInputSchema,
    outputSchema: ListOutputSchema,
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  })
  public listRecentActivity(
    input: z.infer<typeof ActivityInputSchema>,
    _context: Context,
  ): z.infer<typeof ListOutputSchema> {
    const anchor = Date.parse(`${this.repository.snapshotDate}T23:59:59.999Z`);
    const rangeStart =
      input.period === 'today'
        ? Date.parse(`${this.repository.snapshotDate}T00:00:00.000Z`)
        : anchor - 6 * 24 * 60 * 60 * 1000;
    const items = this.repository
      .list('activities')
      .filter((activity) => {
        const timestamp = recordDate(activity);
        return timestamp >= rangeStart && timestamp <= anchor;
      })
      .sort((left, right) => recordDate(right) - recordDate(left))
      .map(toPublicRecord);
    return { items };
  }

  @Tool({
    name: 'crm_mark_follow_up_complete',
    title: 'Complete Follow-up',
    description: 'Mark an investor follow-up or activity as complete.',
    parameters: CompleteInputSchema,
    outputSchema: CompleteOutputSchema,
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  })
  public markFollowUpComplete(
    input: z.infer<typeof CompleteInputSchema>,
    _context: Context,
  ): z.infer<typeof CompleteOutputSchema> {
    const item = this.repository.update('activities', input.id, {
      data: { completed: true, status: 'Completed' },
    });
    if (!item) {
      throw new Error(`Unknown follow-up "${input.id}".`);
    }
    return { item: toPublicRecord(item), completed: true };
  }

  @Tool({
    name: 'outlook_list_calendar',
    title: 'List Calendar',
    description: 'List investor-relations meetings and prospect touchpoints from the demo CRM.',
    parameters: EmptyInputSchema,
    outputSchema: ListOutputSchema,
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  })
  public listCalendar(
    _input: z.infer<typeof EmptyInputSchema>,
    _context: Context,
  ): z.infer<typeof ListOutputSchema> {
    const items = this.repository
      .list('calendarEvents')
      .sort((left, right) => recordDate(left) - recordDate(right))
      .map(toPublicRecord);
    return { items };
  }

  @Tool({
    name: 'outlook_list_messages',
    title: 'List Messages',
    description: 'List dummy investor-relations email messages imported from the reference data.',
    parameters: EmptyInputSchema,
    outputSchema: ListOutputSchema,
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
  })
  public listMessages(
    _input: z.infer<typeof EmptyInputSchema>,
    _context: Context,
  ): z.infer<typeof ListOutputSchema> {
    const items = this.repository
      .list('messages')
      .sort((left, right) => recordDate(right) - recordDate(left))
      .map(toPublicRecord);
    return { items };
  }
}
