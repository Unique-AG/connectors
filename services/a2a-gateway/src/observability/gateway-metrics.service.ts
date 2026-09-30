import { Injectable } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';

export type Direction = 'inbound' | 'outbound';

/**
 * Operational metrics. Labels are tenant, direction and outcome only: never user, space, message
 * or content, which stay in the usage API and the database.
 */
@Injectable()
export class GatewayMetrics {
  private readonly finished: Counter;
  private readonly duration: Histogram;
  private readonly bytes: Counter;
  private readonly rejected: Counter;
  private readonly active = new Map<string, number>();
  private readonly stuck = new Map<string, number>();

  public constructor(metrics: MetricService) {
    this.finished = metrics.getCounter('a2a_gateway_runs_finished_total', {
      description: 'Finished A2A runs by tenant, direction and final state',
    });
    this.duration = metrics.getHistogram('a2a_gateway_run_duration_seconds', {
      description: 'Wall-clock duration of finished A2A runs',
      unit: 's',
    });
    this.bytes = metrics.getCounter('a2a_gateway_bytes_total', {
      description: 'Content bytes exchanged with A2A peers',
      unit: 'By',
    });
    this.rejected = metrics.getCounter('a2a_gateway_quota_rejections_total', {
      description: 'Requests rejected by a concurrency quota',
    });
    metrics
      .getObservableGauge('a2a_gateway_active_runs', {
        description: 'Non-terminal A2A runs, as of the last maintenance tick',
      })
      .addCallback((result) => {
        for (const [key, value] of this.active) {
          result.observe(value, JSON.parse(key) as Record<string, string>);
        }
      });
    metrics
      .getObservableGauge('a2a_gateway_stuck_runs', {
        description: 'Runs without progress beyond the recovery threshold, as of the last tick',
      })
      .addCallback((result) => {
        for (const [key, value] of this.stuck) {
          result.observe(value, JSON.parse(key) as Record<string, string>);
        }
      });
  }

  public runFinished(companyId: string, direction: Direction, state: string, startedAt: Date) {
    const labels = { company_id: companyId, direction, state };
    this.finished.add(1, labels);
    this.duration.record((Date.now() - startedAt.getTime()) / 1000, labels);
  }

  public bytesExchanged(
    companyId: string,
    direction: Direction,
    flow: 'in' | 'out',
    bytes: number,
  ) {
    if (bytes > 0) {
      this.bytes.add(bytes, { company_id: companyId, direction, flow });
    }
  }

  public quotaRejected(companyId: string, direction: Direction, scope: string) {
    this.rejected.add(1, { company_id: companyId, direction, scope });
  }

  public observeRuns(
    counts: { companyId: string; direction: Direction; active: number; stuck: number }[],
  ) {
    this.active.clear();
    this.stuck.clear();
    for (const count of counts) {
      const key = JSON.stringify({ company_id: count.companyId, direction: count.direction });
      this.active.set(key, count.active);
      this.stuck.set(key, count.stuck);
    }
  }
}
