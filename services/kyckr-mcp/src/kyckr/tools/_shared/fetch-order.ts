import { Logger } from '@nestjs/common';
import { KyckrApiError, type KyckrHttpClient } from '../../kyckr-http.client';
import {
  type KyckrOrderDocument,
  KyckrOrderDownloadEnvelopeSchema,
} from '../../schemas/kyckr-order-document.schemas';
import type { KyckrOrderStatus } from '../../schemas/kyckr-response.schemas';

const logger = new Logger('FetchOrder');

const PDF_NOT_SUPPORTED_DETAIL =
  'This document is only available as a PDF. PDF delivery is not yet supported; support is coming soon.';

export type FetchOrderResult =
  | { kind: 'json'; documentJson: KyckrOrderDocument }
  | { kind: 'absent'; detail: string };

/**
 * Resolves the document body for a completed Kyckr order via
 * `GET /orders/{orderId}/download?format=json`.
 *
 * Returns `{ kind: 'json', documentJson }` when the registry exposes a JSON
 * projection. When no JSON projection exists (empty body, `Data: null`, or
 * 404 from the JSON endpoint) returns `{ kind: 'absent' }` with a short
 * message indicating that the document is PDF-only and that PDF delivery is
 * not yet supported. Non-404 upstream errors are re-thrown so the caller
 * surfaces them as a structured `{ success: false, statusCode, … }`
 * envelope.
 */
export async function fetchOrder(
  client: KyckrHttpClient,
  orderId: string,
  status: KyckrOrderStatus | undefined,
): Promise<FetchOrderResult> {
  if (status !== 'Success') {
    return { kind: 'absent', detail: '' };
  }

  const downloadPath = `/orders/${encodeURIComponent(orderId)}/download`;
  try {
    const raw = await client.get<unknown>(downloadPath, { format: 'json' });
    if (raw === undefined || raw === null) {
      logger.debug({ orderId }, 'fetch_order: empty JSON body, document is PDF-only');
      return { kind: 'absent', detail: PDF_NOT_SUPPORTED_DETAIL };
    }
    const envelope = KyckrOrderDownloadEnvelopeSchema.parse(raw);
    if (!envelope.Data) {
      logger.debug({ orderId }, 'fetch_order: envelope.Data is null, document is PDF-only');
      return { kind: 'absent', detail: PDF_NOT_SUPPORTED_DETAIL };
    }
    return { kind: 'json', documentJson: envelope.Data };
  } catch (err) {
    if (err instanceof KyckrApiError && err.status === 404) {
      logger.debug(
        { orderId, correlationId: err.correlationId },
        'fetch_order: JSON 404, document is PDF-only',
      );
      return { kind: 'absent', detail: PDF_NOT_SUPPORTED_DETAIL };
    }
    throw err;
  }
}

export function appendDetail(
  existing: string | undefined,
  addition: string | undefined,
): string | undefined {
  if (!addition) {
    return existing;
  }
  if (!existing) {
    return addition;
  }
  return `${existing} ${addition}`;
}

/**
 * Removes the `links` field (raw Kyckr download URLs) from an order-data
 * payload before it is surfaced to the agent. The document body is delivered
 * via `data.documentJson`; download URLs add no value and only encourage the
 * agent to regurgitate them in user-facing replies.
 */
export function stripLinks<T>(data: T | undefined): T | undefined {
  if (!data || typeof data !== 'object') {
    return data;
  }
  const { links: _drop, ...rest } = data as Record<string, unknown>;
  return rest as T;
}
