import { Injectable } from '@nestjs/common';
import type { Counter } from '@opentelemetry/api';
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
  private readonly callCounters: Record<KyckrToolName, Counter>;
  private readonly creditsConsumed: Counter;

  public constructor(metricService: MetricService) {
    this.callCounters = {
      search_companies: metricService.getCounter('kyckr_search_companies_calls_total', {
        description: 'Number of `search_companies` MCP tool calls',
      }),
      get_lite_profile: metricService.getCounter('kyckr_lite_profile_fetches_total', {
        description: 'Number of `get_lite_profile` MCP tool calls',
      }),
      get_enhanced_profile: metricService.getCounter('kyckr_enhanced_profile_fetches_total', {
        description: 'Number of `get_enhanced_profile` MCP tool calls',
      }),
      list_company_documents: metricService.getCounter('kyckr_company_documents_list_calls_total', {
        description: 'Number of `list_company_documents` MCP tool calls',
      }),
      create_document_order: metricService.getCounter('kyckr_document_orders_total', {
        description: 'Number of `create_document_order` MCP tool calls',
      }),
      get_order: metricService.getCounter('kyckr_get_order_calls_total', {
        description: 'Number of `get_order` MCP tool calls',
      }),
      list_orders: metricService.getCounter('kyckr_list_orders_calls_total', {
        description: 'Number of `list_orders` MCP tool calls',
      }),
    };

    this.creditsConsumed = metricService.getCounter('kyckr_credits_consumed_total', {
      description: 'Kyckr credits consumed, attributed to the MCP tool that triggered the call',
    });
  }

  public recordToolCall(tool: KyckrToolName, result: KyckrToolCallResult): void {
    this.callCounters[tool].add(1, { result });
  }

  public recordCreditsConsumed(tool: KyckrToolName, cost: { value?: number } | undefined): void {
    if (cost?.value && cost.value > 0) {
      this.creditsConsumed.add(cost.value, { tool });
    }
  }
}
