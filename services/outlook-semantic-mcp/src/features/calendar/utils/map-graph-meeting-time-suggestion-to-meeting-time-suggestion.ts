import type { GraphMeetingTimeSuggestion } from '../calendar.schemas';

interface AttendeeAvailability {
  email: string | null;
  availability: string | null;
}

export interface MeetingTimeSuggestion {
  start: { dateTime: string; timeZone: string | null };
  end: { dateTime: string; timeZone: string | null };
  confidence: number | null;
  organizerAvailability: string | null;
  suggestionReason: string | null;
  attendeeAvailability: AttendeeAvailability[];
}

export function mapGraphMeetingTimeSuggestionToMeetingTimeSuggestion(
  item: GraphMeetingTimeSuggestion,
): MeetingTimeSuggestion {
  return {
    start: {
      dateTime: item.meetingTimeSlot?.start?.dateTime ?? '',
      timeZone: item.meetingTimeSlot?.start?.timeZone ?? null,
    },
    end: {
      dateTime: item.meetingTimeSlot?.end?.dateTime ?? '',
      timeZone: item.meetingTimeSlot?.end?.timeZone ?? null,
    },
    confidence: item.confidence ?? null,
    organizerAvailability: item.organizerAvailability ?? null,
    suggestionReason: item.suggestionReason ?? null,
    attendeeAvailability: (item.attendeeAvailability ?? []).map((entry) => ({
      email: entry.attendee?.emailAddress?.address ?? null,
      availability: entry.availability ?? null,
    })),
  };
}
