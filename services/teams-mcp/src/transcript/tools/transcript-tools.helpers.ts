import { TRANSCRIPT_MIME_TYPE } from '~/unique/unique.consts';
import { type MetadataFilter, UniqueQLOperator } from '~/unique/unique.dtos';

export interface TranscriptFilterInput {
  subject?: string;
  dateFrom?: string;
  dateTo?: string;
  organizer?: string;
  participant?: string;
}

export interface ParsedTranscriptMetadata {
  meetingDate?: string;
  startDatetime?: string;
  endDatetime?: string;
  organizer?: string;
  participants?: string[];
}

/**
 * Builds the shared UniqueQL metadata filter for transcript tools.
 * Restricts to the VTT mime type (transcripts, not recordings); optional filters
 * narrow by subject, date range, organizer, and participant. Discovery is scoped to
 * Teams content by the `sourceKind` argument on the tool calls, not by folder path.
 */
export function buildTranscriptFilter(input: TranscriptFilterInput): MetadataFilter {
  const conditions: MetadataFilter[] = [
    // Type filter: only return transcripts (VTT files), not recordings
    {
      path: ['mimeType'],
      operator: UniqueQLOperator.EQUALS,
      value: TRANSCRIPT_MIME_TYPE,
    },
  ];

  if (input.subject) {
    conditions.push({
      path: ['title'],
      operator: UniqueQLOperator.CONTAINS,
      value: input.subject,
    });
  }

  if (input.dateFrom) {
    conditions.push({
      path: ['metadata', 'date'],
      operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
      value: input.dateFrom,
    });
  }

  if (input.dateTo) {
    conditions.push({
      path: ['metadata', 'date'],
      operator: UniqueQLOperator.LESS_THAN_OR_EQUAL,
      value: input.dateTo,
    });
  }

  if (input.organizer) {
    conditions.push({
      or: [
        {
          path: ['metadata', 'organizer_name'],
          operator: UniqueQLOperator.CONTAINS,
          value: input.organizer,
        },
        {
          path: ['metadata', 'organizer_email'],
          operator: UniqueQLOperator.CONTAINS,
          value: input.organizer,
        },
      ],
    });
  }

  if (input.participant) {
    conditions.push({
      or: [
        {
          path: ['metadata', 'participant_names'],
          operator: UniqueQLOperator.CONTAINS,
          value: input.participant,
        },
        {
          path: ['metadata', 'participant_emails'],
          operator: UniqueQLOperator.CONTAINS,
          value: input.participant,
        },
      ],
    });
  }

  return { and: conditions };
}

/**
 * Extracts well-known transcript metadata fields from a raw KB content metadata object.
 */
export function parseTranscriptMetadata(
  metadata: Record<string, unknown> | null,
): ParsedTranscriptMetadata {
  const participantNames = metadata?.participant_names;
  const participants =
    typeof participantNames === 'string'
      ? participantNames
          .split(',')
          .map((p) => p.trim())
          .filter(Boolean)
      : undefined;

  return {
    meetingDate: typeof metadata?.date === 'string' ? metadata.date : undefined,
    startDatetime:
      typeof metadata?.start_datetime === 'string' ? metadata.start_datetime : undefined,
    endDatetime: typeof metadata?.end_datetime === 'string' ? metadata.end_datetime : undefined,
    organizer: typeof metadata?.organizer_name === 'string' ? metadata.organizer_name : undefined,
    participants: participants?.length ? participants : undefined,
  };
}
