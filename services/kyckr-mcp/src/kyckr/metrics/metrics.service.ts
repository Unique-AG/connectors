import { Injectable } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';

export const KYCKR_TOOL_NAMES = [
  'search_companies',
  'get_lite_profile',
  'get_enhanced_profile',
  'list_company_documents',
  'create_document_order',
  'get_order',
  'list_orders',
] as const;

export type KyckrToolName = (typeof KYCKR_TOOL_NAMES)[number];

export type KyckrToolCallResult = 'success' | 'error';

@Injectable()
export class Metrics {
  private readonly toolCalls: Counter;
  private readonly toolCallDuration: Histogram;
  private readonly creditsConsumed: Counter;
  private readonly apiRequests: Counter;
  private readonly apiRequestDuration: Histogram;

  public constructor(metricService: MetricService) {
    this.toolCalls = metricService.getCounter('kyckr_tool_calls_total', {
      description: 'Number of Kyckr MCP tool calls, labelled by tool and result',
    });

    this.toolCallDuration = metricService.getHistogram('kyckr_tool_call_duration_ms', {
      description: 'Duration of Kyckr MCP tool calls in milliseconds, labelled by tool and result',
    });

    this.creditsConsumed = metricService.getCounter('kyckr_credits_consumed_total', {
      description: 'Kyckr credits consumed, attributed to the MCP tool that triggered the call',
    });

    this.apiRequests = metricService.getCounter('kyckr_api_requests_total', {
      description: 'Total Kyckr API requests, labelled by method, path, and status',
    });

    this.apiRequestDuration = metricService.getHistogram('kyckr_api_request_duration_ms', {
      description: 'Kyckr API request duration in milliseconds, labelled by method and path',
    });
  }

  public recordToolCall(tool: KyckrToolName, result: KyckrToolCallResult): void {
    this.toolCalls.add(1, { tool, result });
  }

  public recordToolDuration(
    tool: KyckrToolName,
    result: KyckrToolCallResult,
    durationMs: number,
  ): void {
    this.toolCallDuration.record(durationMs, { tool, result });
  }

  public recordCreditsConsumed(tool: KyckrToolName, cost: { value?: number } | undefined): void {
    if (cost?.value && cost.value > 0) {
      this.creditsConsumed.add(cost.value, { tool });
    }
  }

  public recordApiRequest(params: {
    method: string;
    path: string;
    status: number;
    durationMs: number;
  }): void {
    const { method, path, status, durationMs } = params;
    this.apiRequests.add(1, { method, path, status: String(status) });
    this.apiRequestDuration.record(durationMs, { method, path });
  }
}
