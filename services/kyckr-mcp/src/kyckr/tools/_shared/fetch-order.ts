import { Logger } from '@nestjs/common';
import { KyckrApiError, type KyckrHttpClient } from '../../kyckr-http.client';
import {
  type KyckrOrderDocument,
  KyckrOrderDownloadEnvelopeSchema,
} from '../../schemas/kyckr-order-document.schemas';
import type { KyckrOrderStatus } from '../../schemas/kyckr-response.schemas';

const logger = new Logger('FetchOrder');

export const MAX_PDF_BYTES = 8 * 1024 * 1024;

const DOCUMENT_UNAVAILABLE_DETAIL = 'Document body unavailable.';

export type FetchOrderResult =
  | { kind: 'json'; documentJson: KyckrOrderDocument }
  | { kind: 'pdf'; pdfBase64: string; sizeBytes: number }
  | { kind: 'absent'; detail: string };

/**
 * Resolves the document body for a completed Kyckr order.
 *
 * Strategy: try `GET /orders/{orderId}/download?format=json` first - the
 * structured projection is the preferred deliverable. Only if that returns
 * empty, `Data: null`, or 404, fall back to the PDF representation of the
 * SAME order via `GET /orders/{orderId}/download?format=pdf` (no second
 * order is placed - just a different format projection of the same one).
 * Above `MAX_PDF_BYTES` the PDF is dropped (clients can't realistically
 * embed it) and a size note is emitted instead. Non-404 upstream errors are
 * re-thrown so the caller surfaces them as a structured
 * `{ success: false, statusCode, … }` envelope.
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
    if (raw !== undefined && raw !== null) {
      const envelope = KyckrOrderDownloadEnvelopeSchema.parse(raw);
      if (envelope.Data) {
        return { kind: 'json', documentJson: envelope.Data };
      }
      logger.debug({ orderId }, 'fetch_order: envelope.Data is null, falling back to PDF');
    } else {
      logger.debug({ orderId }, 'fetch_order: empty JSON body, falling back to PDF');
    }
  } catch (err) {
    if (err instanceof KyckrApiError && err.status === 404) {
      logger.debug(
        { orderId, correlationId: err.correlationId },
        'fetch_order: JSON 404, falling back to PDF',
      );
    } else {
      throw err;
    }
  }

  try {
    const pdfBuffer = await client.getBinary(downloadPath, { format: 'pdf' });
    if (!pdfBuffer || pdfBuffer.byteLength === 0) {
      logger.debug({ orderId }, 'fetch_order: PDF body empty');
      return { kind: 'absent', detail: DOCUMENT_UNAVAILABLE_DETAIL };
    }
    if (pdfBuffer.byteLength > MAX_PDF_BYTES) {
      const mb = (pdfBuffer.byteLength / 1024 / 1024).toFixed(1);
      logger.debug(
        { orderId, sizeBytes: pdfBuffer.byteLength },
        'fetch_order: PDF exceeds embed cap',
      );
      return {
        kind: 'absent',
        detail: `Document body too large to embed (${mb} MB).`,
      };
    }
    return {
      kind: 'pdf',
      pdfBase64: pdfBuffer.toString('base64'),
      sizeBytes: pdfBuffer.byteLength,
    };
  } catch (err) {
    if (err instanceof KyckrApiError && err.status === 404) {
      logger.debug(
        { orderId, correlationId: err.correlationId },
        'fetch_order: PDF 404, document unavailable',
      );
      return { kind: 'absent', detail: DOCUMENT_UNAVAILABLE_DETAIL };
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
 * via `data.documentJson` or as an embedded PDF resource block on the tool
 * response, so download URLs add no value and only encourage the agent to
 * regurgitate them in user-facing replies.
 */
export function stripLinks<T>(data: T | undefined): T | undefined {
  if (!data || typeof data !== 'object') {
    return data;
  }
  const { links: _drop, ...rest } = data as Record<string, unknown>;
  return rest as T;
}
