import { elapsedMilliseconds } from '@unique-ag/utils';
import { Injectable } from '@nestjs/common';
import type { Counter, Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';

export const TEMENOS_TOOL_NAMES = [
  'get_guarantees',
  'get_expiring_limits',
  'get_review_limits',
  'get_limit_master_groups',
  'get_shared_limits',
  'get_letter_of_credit_inco_terms',
  'get_letter_of_credit_tenors',
  'get_nostro_accounts',
  'get_vostro_accounts',
  'get_payment_stops',
  'get_derivative_option_assigns',
  'get_derivative_option_exercises',
  'get_derivative_option_expires',
  'get_repo_position_movements',
  'get_repo_positions',
  'get_reverse_repo_position_movements',
  'get_reverse_repo_positions',
  'get_pending_payments',
  'get_payment_fees',
  'get_transaction_stop_investigations',
  'get_customer_relationships',
  'get_customer_secure_messages',
  'get_customer_prospects',
  'get_participants',
  'get_external_user_preferences',
  'get_interest_conditions',
  'get_account_officers',
  'get_balance_types',
  'get_cheque_types',
  'get_countries',
  'get_industries',
  'get_language_codes',
  'get_brokers',
  'get_companies',
  'get_purposes',
  'get_sectors',
  'get_categories',
  'get_dealers',
  'get_rate_texts',
  'get_system_dates',
  'get_lookups',
  'get_utility_beneficiaries',
  'get_us_beneficial_owner_types',
  'get_us_states',
  'get_us_customer_ratings',
  'get_us_hold_types',
  'get_us_fdic_classcodes',
  'get_us_loan_covenants',
  'get_us_industries',
] as const;

export type TemenosToolName = (typeof TEMENOS_TOOL_NAMES)[number];

export type TemenosToolCallResult = 'success' | 'error';

@Injectable()
export class Metrics {
  private readonly toolCallDuration: Histogram;
  private readonly apiRequests: Counter;
  private readonly apiRequestDuration: Histogram;

  public constructor(metricService: MetricService) {
    this.toolCallDuration = metricService.getHistogram('temenos_tool_call_duration_ms', {
      description: 'Duration of Temenos MCP tool calls in milliseconds, labelled by tool and result',
    });

    this.apiRequests = metricService.getCounter('temenos_api_requests_total', {
      description: 'Total Temenos API requests, labelled by method, path, and status',
    });

    this.apiRequestDuration = metricService.getHistogram('temenos_api_request_duration_ms', {
      description: 'Temenos API request duration in milliseconds, labelled by path',
    });
  }

  public recordToolDuration(
    tool: TemenosToolName,
    result: TemenosToolCallResult,
    startTime: Date | number,
  ): void {
    this.toolCallDuration.record(elapsedMilliseconds(startTime), { tool, result });
  }

  public recordApiRequest({
    path,
    status,
    durationMs,
  }: {
    path: string;
    status: number;
    durationMs: number;
  }): void {
    this.apiRequests.add(1, { path, status: String(status) });
    this.apiRequestDuration.record(durationMs, { path });
  }
}
