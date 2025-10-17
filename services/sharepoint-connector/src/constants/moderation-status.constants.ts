export const ModerationStatus = {
  Approved: 0,
  Rejected: 1,
  Pending: 2,
} as const;

export type ModerationStatusValue = (typeof ModerationStatus)[keyof typeof ModerationStatus];

export function isModerationStatusApproved(status: unknown): status is 0 {
  return status === ModerationStatus.Approved;
}
