import { Email } from '@/lib/powersync/schema';

export interface EmailThread {
  id: string;
  subject: string;
  emails: Email[];
  lastDate: Date;
  isRead: boolean;
  hasAttachments: boolean;
}

export type ProcessingStatus = 'pending' | 'processing' | 'completed' | 'error';

export function getProcessingStatus(email: Email): ProcessingStatus {
  if (email.ingestionCompletedAt) {
    return 'completed';
  }
  if (email.ingestionLastError) {
    return 'error';
  }
  if (email.ingestionLastAttemptAt) {
    return 'processing';
  }
  return 'pending';
}

export function parseFromField(from: string | null): { name: string; email: string } {
  if (!from) {
    return { name: 'Unknown', email: '' };
  }
  try {
    const parsed = JSON.parse(from) as { name: string | null; address: string };
    return {
      name: parsed.name || parsed.address,
      email: parsed.address,
    };
  } catch {
    return { name: from, email: from };
  }
}
