import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { KyckrConfig } from '~/config';
import { KyckrApiError, type KyckrHttpClient } from '../kyckr-http.client';
import type { Metrics } from '../metrics';
import {
  CreateDocumentOrderInputSchema,
  CreateDocumentOrderQuery,
} from './create-document-order/create-document-order.query';
import { GetEnhancedProfileQuery } from './get-enhanced-profile/get-enhanced-profile.query';
import { GetLiteProfileQuery } from './get-lite-profile/get-lite-profile.query';
import { GetOrderInputSchema, GetOrderQuery } from './get-order/get-order.query';
import { ListCompanyDocumentsQuery } from './list-company-documents/list-company-documents.query';
import { ListOrdersInputSchema, ListOrdersQuery } from './list-orders/list-orders.query';
import {
  SearchCompaniesInputSchema,
  SearchCompaniesQuery,
} from './search-companies/search-companies.query';

const mockKyckrClient = {
  get: vi.fn(),
  post: vi.fn(),
};

const mockMetrics = {
  recordToolCall: vi.fn(),
  recordCreditsConsumed: vi.fn(),
};

const stubConfig = {
  apiBaseUrl: 'https://api.example.com',
  apiKey: { value: 'test-api-key' },
  defaultCustomerReference: 'customer-ref-123',
  defaultContactEmail: 'ops@example.com',
} as KyckrConfig;

function makeKyckrApiError(
  status: number,
  path: string,
  message: string,
  correlationId = 'corr-123',
): KyckrApiError {
  return new KyckrApiError(status, path, message, correlationId);
}

describe('Kyckr query schemas', () => {
  it('normalizes and validates search_companies input', () => {
    const result = SearchCompaniesInputSchema.parse({
      name: '  Acme Ltd  ',
      isoCode: 'gb',
    });

    expect(result).toEqual({
      name: 'Acme Ltd',
      isoCode: 'GB',
    });
  });

  it('rejects search_companies input without name or companyNumber', () => {
    expect(() => SearchCompaniesInputSchema.parse({ isoCode: 'GB' })).toThrow(
      'Provide either `name` or `companyNumber`.',
    );
  });

  it('stringifies numeric get_order ids', () => {
    expect(GetOrderInputSchema.parse({ orderId: 12345 }).orderId).toBe('12345');
  });

  it('normalizes list_orders isoCode input', () => {
    expect(ListOrdersInputSchema.parse({ isoCode: 'ie' }).isoCode).toBe('IE');
  });

  it('trims create_document_order product ids', () => {
    expect(
      CreateDocumentOrderInputSchema.parse({
        kyckrId: 'GB|123',
        productId: '  PROD-1  ',
      }).productId,
    ).toBe('PROD-1');
  });
});

describe('SearchCompaniesQuery', () => {
  let unit: SearchCompaniesQuery;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new SearchCompaniesQuery(
      mockKyckrClient as unknown as KyckrHttpClient,
      mockMetrics as unknown as Metrics,
    );
  });

  it('returns matched companies on success', async () => {
    const response = {
      correlationId: 'corr-search',
      cost: { value: 0 },
      data: [{ id: 'GB|123', companyName: 'Acme Ltd' }],
    };
    mockKyckrClient.get.mockResolvedValueOnce(response);

    const result = await unit.run({ name: 'Acme Ltd', isoCode: 'GB' });

    expect(mockKyckrClient.get).toHaveBeenCalledWith('/companies', {
      name: 'Acme Ltd',
      companyNumber: undefined,
      isoCode: 'GB',
    });
    expect(result).toEqual({ success: true, ...response });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('search_companies', 'success');
    expect(mockMetrics.recordCreditsConsumed).toHaveBeenCalledWith('search_companies', {
      value: 0,
    });
  });

  it('returns a structured failure for Kyckr API errors', async () => {
    mockKyckrClient.get.mockRejectedValueOnce(
      makeKyckrApiError(404, '/companies', 'No matching companies', 'corr-search-fail'),
    );

    await expect(unit.run({ companyNumber: '12345678' })).resolves.toEqual({
      success: false,
      statusCode: 404,
      message: 'No matching companies',
      correlationId: 'corr-search-fail',
    });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('search_companies', 'error');
    expect(mockMetrics.recordCreditsConsumed).not.toHaveBeenCalled();
  });

  it('rethrows unexpected errors', async () => {
    const error = new Error('network failure');
    mockKyckrClient.get.mockRejectedValueOnce(error);

    await expect(unit.run({ name: 'Acme Ltd' })).rejects.toThrow('network failure');
  });
});

describe('GetLiteProfileQuery', () => {
  let unit: GetLiteProfileQuery;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new GetLiteProfileQuery(
      mockKyckrClient as unknown as KyckrHttpClient,
      mockMetrics as unknown as Metrics,
      stubConfig,
    );
  });

  it('returns the lite profile and forwards the customer reference', async () => {
    const response = {
      correlationId: 'corr-lite',
      cost: { value: 2 },
      data: { companyName: 'Acme Ltd' },
    };
    mockKyckrClient.get.mockResolvedValueOnce(response);

    const result = await unit.run({ kyckrId: 'GB|123' });

    expect(mockKyckrClient.get).toHaveBeenCalledWith('/companies/GB%7C123/lite', {
      customerReference: 'customer-ref-123',
    });
    expect(result).toEqual({ success: true, ...response });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('get_lite_profile', 'success');
    expect(mockMetrics.recordCreditsConsumed).toHaveBeenCalledWith('get_lite_profile', {
      value: 2,
    });
  });

  it('returns a structured failure for Kyckr API errors', async () => {
    mockKyckrClient.get.mockRejectedValueOnce(
      makeKyckrApiError(403, '/companies/GB%7C123/lite', 'Profile unavailable', 'corr-lite-fail'),
    );

    await expect(unit.run({ kyckrId: 'GB|123' })).resolves.toEqual({
      success: false,
      statusCode: 403,
      message: 'Profile unavailable',
      correlationId: 'corr-lite-fail',
    });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('get_lite_profile', 'error');
    expect(mockMetrics.recordCreditsConsumed).not.toHaveBeenCalled();
  });

  it('rethrows unexpected errors', async () => {
    const error = new Error('timeout');
    mockKyckrClient.get.mockRejectedValueOnce(error);

    await expect(unit.run({ kyckrId: 'GB|123' })).rejects.toThrow('timeout');
  });
});

describe('GetEnhancedProfileQuery', () => {
  let unit: GetEnhancedProfileQuery;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new GetEnhancedProfileQuery(
      mockKyckrClient as unknown as KyckrHttpClient,
      mockMetrics as unknown as Metrics,
      stubConfig,
    );
  });

  it('returns the enhanced profile and forwards the customer reference', async () => {
    const response = {
      correlationId: 'corr-enhanced',
      cost: { value: 5 },
      data: {
        companyName: 'Acme Ltd',
        representatives: { individuals: [{ type: 'Person' }] },
      },
    };
    mockKyckrClient.get.mockResolvedValueOnce(response);

    const result = await unit.run({ kyckrId: 'GB|123' });

    expect(mockKyckrClient.get).toHaveBeenCalledWith('/companies/GB%7C123/enhanced', {
      customerReference: 'customer-ref-123',
    });
    expect(result).toEqual({ success: true, ...response });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('get_enhanced_profile', 'success');
    expect(mockMetrics.recordCreditsConsumed).toHaveBeenCalledWith('get_enhanced_profile', {
      value: 5,
    });
  });

  it('returns a structured failure for Kyckr API errors', async () => {
    mockKyckrClient.get.mockRejectedValueOnce(
      makeKyckrApiError(
        405,
        '/companies/GB%7C123/enhanced',
        'Enhanced profile requires ordering',
        'corr-enhanced-fail',
      ),
    );

    await expect(unit.run({ kyckrId: 'GB|123' })).resolves.toEqual({
      success: false,
      statusCode: 405,
      message: 'Enhanced profile requires ordering',
      correlationId: 'corr-enhanced-fail',
    });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('get_enhanced_profile', 'error');
    expect(mockMetrics.recordCreditsConsumed).not.toHaveBeenCalled();
  });

  it('rethrows unexpected errors', async () => {
    const error = new Error('boom');
    mockKyckrClient.get.mockRejectedValueOnce(error);

    await expect(unit.run({ kyckrId: 'GB|123' })).rejects.toThrow('boom');
  });
});

describe('ListCompanyDocumentsQuery', () => {
  let unit: ListCompanyDocumentsQuery;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new ListCompanyDocumentsQuery(
      mockKyckrClient as unknown as KyckrHttpClient,
      mockMetrics as unknown as Metrics,
      stubConfig,
    );
  });

  it('returns company documents and continuation metadata', async () => {
    const response = {
      correlationId: 'corr-docs',
      cost: { value: 1 },
      continuationKey: 'next-page-token',
      data: [
        {
          id: 'DOC-1',
          name: 'Annual Accounts',
          deliveryTimeMinutes: 15,
          documentFormat: ['application/pdf'],
        },
      ],
    };
    mockKyckrClient.get.mockResolvedValueOnce(response);

    const result = await unit.run({ kyckrId: 'GB|123', continuationKey: 'current-page-token' });

    expect(mockKyckrClient.get).toHaveBeenCalledWith('/companies/GB%7C123/documents', {
      customerReference: 'customer-ref-123',
      continuationKey: 'current-page-token',
    });
    expect(result).toEqual({ success: true, ...response });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('list_company_documents', 'success');
    expect(mockMetrics.recordCreditsConsumed).toHaveBeenCalledWith('list_company_documents', {
      value: 1,
    });
  });

  it('returns a structured failure for Kyckr API errors', async () => {
    mockKyckrClient.get.mockRejectedValueOnce(
      makeKyckrApiError(
        404,
        '/companies/GB%7C123/documents',
        'Company not found',
        'corr-docs-fail',
      ),
    );

    await expect(unit.run({ kyckrId: 'GB|123' })).resolves.toEqual({
      success: false,
      statusCode: 404,
      message: 'Company not found',
      correlationId: 'corr-docs-fail',
    });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('list_company_documents', 'error');
    expect(mockMetrics.recordCreditsConsumed).not.toHaveBeenCalled();
  });

  it('rethrows unexpected errors', async () => {
    const error = new Error('upstream unavailable');
    mockKyckrClient.get.mockRejectedValueOnce(error);

    await expect(unit.run({ kyckrId: 'GB|123' })).rejects.toThrow('upstream unavailable');
  });
});

describe('CreateDocumentOrderQuery', () => {
  let unit: CreateDocumentOrderQuery;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new CreateDocumentOrderQuery(
      mockKyckrClient as unknown as KyckrHttpClient,
      mockMetrics as unknown as Metrics,
      stubConfig,
    );
  });

  it('creates an order with the configured customer reference and contact email', async () => {
    const response = {
      correlationId: 'corr-order-create',
      cost: { value: 3 },
      data: {
        orderId: 'ORD-1',
        status: 'Pending',
      },
    };
    mockKyckrClient.post.mockResolvedValueOnce(response);

    const result = await unit.run({ kyckrId: 'GB|123', productId: 'DOC-1' });

    expect(mockKyckrClient.post).toHaveBeenCalledWith('/orders', {
      kyckrId: 'GB|123',
      productId: 'DOC-1',
      customerReference: 'customer-ref-123',
      contactEmail: 'ops@example.com',
    });
    expect(result).toEqual({ success: true, ...response });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('create_document_order', 'success');
    expect(mockMetrics.recordCreditsConsumed).toHaveBeenCalledWith('create_document_order', {
      value: 3,
    });
  });

  it('returns a structured failure for Kyckr API errors', async () => {
    mockKyckrClient.post.mockRejectedValueOnce(
      makeKyckrApiError(400, '/orders', 'Product id is invalid', 'corr-order-create-fail'),
    );

    await expect(unit.run({ kyckrId: 'GB|123', productId: 'DOC-1' })).resolves.toEqual({
      success: false,
      statusCode: 400,
      message: 'Product id is invalid',
      correlationId: 'corr-order-create-fail',
    });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('create_document_order', 'error');
    expect(mockMetrics.recordCreditsConsumed).not.toHaveBeenCalled();
  });

  it('rethrows unexpected errors', async () => {
    const error = new Error('socket hang up');
    mockKyckrClient.post.mockRejectedValueOnce(error);

    await expect(unit.run({ kyckrId: 'GB|123', productId: 'DOC-1' })).rejects.toThrow(
      'socket hang up',
    );
  });
});

describe('GetOrderQuery', () => {
  let unit: GetOrderQuery;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new GetOrderQuery(
      mockKyckrClient as unknown as KyckrHttpClient,
      mockMetrics as unknown as Metrics,
    );
  });

  it('returns order details on success', async () => {
    const response = {
      correlationId: 'corr-order',
      cost: { value: 0 },
      data: {
        orderId: 'ORD-1',
        status: 'Success',
        links: {
          document: 'https://downloads.example.com/ORD-1.pdf',
        },
      },
    };
    mockKyckrClient.get.mockResolvedValueOnce(response);

    const result = await unit.run({ orderId: 'ORD-1' });

    expect(mockKyckrClient.get).toHaveBeenCalledWith('/orders/ORD-1');
    expect(result).toEqual({ success: true, ...response });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('get_order', 'success');
    expect(mockMetrics.recordCreditsConsumed).toHaveBeenCalledWith('get_order', { value: 0 });
  });

  it('returns a structured failure for Kyckr API errors', async () => {
    mockKyckrClient.get.mockRejectedValueOnce(
      makeKyckrApiError(404, '/orders/ORD-1', 'Order not found', 'corr-order-fail'),
    );

    await expect(unit.run({ orderId: 'ORD-1' })).resolves.toEqual({
      success: false,
      statusCode: 404,
      message: 'Order not found',
      correlationId: 'corr-order-fail',
    });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('get_order', 'error');
    expect(mockMetrics.recordCreditsConsumed).not.toHaveBeenCalled();
  });

  it('rethrows unexpected errors', async () => {
    const error = new Error('gateway timeout');
    mockKyckrClient.get.mockRejectedValueOnce(error);

    await expect(unit.run({ orderId: 'ORD-1' })).rejects.toThrow('gateway timeout');
  });
});

describe('ListOrdersQuery', () => {
  let unit: ListOrdersQuery;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new ListOrdersQuery(
      mockKyckrClient as unknown as KyckrHttpClient,
      mockMetrics as unknown as Metrics,
    );
  });

  it('returns the paginated orders response on success', async () => {
    const response = {
      correlationId: 'corr-orders',
      cost: { value: 0 },
      data: {
        totalCount: 1,
        pageNumber: 1,
        pageSize: 50,
        orders: [{ orderId: 'ORD-1', status: 'Pending' }],
      },
    };
    mockKyckrClient.get.mockResolvedValueOnce(response);

    const result = await unit.run({
      startDate: '2026-01-01',
      endDate: '2026-01-31',
      isoCode: 'GB',
    });

    expect(mockKyckrClient.get).toHaveBeenCalledWith('/orders', {
      startDate: '2026-01-01',
      endDate: '2026-01-31',
      isoCode: 'GB',
    });
    expect(result).toEqual({ success: true, ...response });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('list_orders', 'success');
    expect(mockMetrics.recordCreditsConsumed).toHaveBeenCalledWith('list_orders', { value: 0 });
  });

  it('returns a structured failure for Kyckr API errors', async () => {
    mockKyckrClient.get.mockRejectedValueOnce(
      makeKyckrApiError(429, '/orders', 'Too many requests', 'corr-orders-fail'),
    );

    await expect(unit.run({ isoCode: 'GB' })).resolves.toEqual({
      success: false,
      statusCode: 429,
      message: 'Too many requests',
      correlationId: 'corr-orders-fail',
    });
    expect(mockMetrics.recordToolCall).toHaveBeenCalledWith('list_orders', 'error');
    expect(mockMetrics.recordCreditsConsumed).not.toHaveBeenCalled();
  });

  it('rethrows unexpected errors', async () => {
    const error = new Error('request aborted');
    mockKyckrClient.get.mockRejectedValueOnce(error);

    await expect(unit.run({ isoCode: 'GB' })).rejects.toThrow('request aborted');
  });
});
