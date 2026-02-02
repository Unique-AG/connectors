import { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { Client } from '@microsoft/microsoft-graph-client';
import { UnauthorizedException } from '@nestjs/common';
import type { Counter, Span } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import { TypeID } from 'typeid-js';
import { OTEL_ATTRIBUTES } from '../utils/otel-attributes';
import { GraphClientFactory } from './graph-client.factory';

export abstract class BaseMsGraphTool {
  protected readonly actionCounter: Counter;
  protected readonly actionFailureCounter: Counter;

  protected constructor(
    protected readonly graphClientFactory: GraphClientFactory,
    protected readonly metricService: MetricService,
  ) {
    this.actionCounter = metricService.getCounter('outlook_actions_total', {
      description: 'Total number of Outlook actions',
    });
    this.actionFailureCounter = metricService.getCounter('outlook_action_failures_total', {
      description: 'Total number of Outlook action failures',
    });
  }

  /**
   * Extracts the user profile ID from the request and creates a Graph client
   * @throws UnauthorizedException if the user is not authenticated
   */
  protected getGraphClient(request: McpAuthenticatedRequest, span?: Span): Client {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    if (span) span.setAttribute(OTEL_ATTRIBUTES.USER_ID, userProfileId);

    return this.graphClientFactory.createClientForUser(
      TypeID.fromString(userProfileId, 'user_profile'),
    );
  }

  protected incrementActionCounter(action: string) {
    if (this.actionCounter) this.actionCounter.add(1, { action });
  }

  protected incrementActionFailureCounter(action: string, reason: string) {
    if (this.actionFailureCounter) this.actionFailureCounter.add(1, { action, reason });
  }
}
