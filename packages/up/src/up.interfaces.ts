export interface UptimeCheckResult {
  name: string;
  status: 'up' | 'down';
  message?: string;
  durationMs: number;
}

export interface UptimeSummary {
  status: 'up' | 'down';
  checks: UptimeCheckResult[];
  timestamp: string;
}

export interface IUptimeCheck {
  checkUp(): Promise<{ status: 'up' | 'down'; message?: string }>;
}
