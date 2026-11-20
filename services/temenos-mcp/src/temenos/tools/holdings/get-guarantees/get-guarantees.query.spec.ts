import { describe, expect, it, vi } from 'vitest';
import type { Metrics } from '../../../metrics';
import { TemenosApiError, type TemenosHttpClient } from '../../../temenos-http.client';
import { GetGuaranteesOutputSchema, GetGuaranteesQuery } from './get-guarantees.query';

const mockHeader = { page_start: 1, page_size: 99, total_size: 1, status: 'success' };
const mockGuarantee = {
  guaranteeId: 'GT2026001',
  customerId: '100100',
  customerName: 'Northwind Traders',
  currency: 'USD',
  amount: 50000,
};

function buildQuery(get: TemenosHttpClient['get']): GetGuaranteesQuery {
  const client = { get } as Pick<TemenosHttpClient, 'get'> as TemenosHttpClient;
  const metrics = { recordToolDuration: vi.fn() } as Pick<Metrics, 'recordToolDuration'> as Metrics;
  return new GetGuaranteesQuery(client, metrics);
}

describe('GetGuaranteesQuery', () => {
  it('returns each guarantee under data with a title and the raw record', async () => {
    const query = buildQuery(
      vi.fn().mockResolvedValue({ header: mockHeader, body: [mockGuarantee] }),
    );

    const result = await query.run({ customerId: '100100' });

    expect(result).toEqual({
      success: true,
      header: mockHeader,
      data: [{ title: 'Guarantee GT2026001 - Northwind Traders', record: mockGuarantee }],
    });
    expect(GetGuaranteesOutputSchema.safeParse(result).success).toBe(true);
  });

  it('returns the upstream status and message on a Temenos error', async () => {
    const query = buildQuery(
      vi
        .fn()
        .mockRejectedValue(new TemenosApiError(404, '/holdings/guarantees/requests', 'Not found')),
    );

    const result = await query.run({});

    expect(result).toEqual({ success: false, statusCode: 404, message: 'Not found' });
  });
});
