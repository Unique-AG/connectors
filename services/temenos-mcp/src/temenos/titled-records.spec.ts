import { describe, expect, it } from 'vitest';
import { toTitledRecords } from './titled-records';

const mockHeader = { page_start: 1, page_size: 99, total_size: 2, status: 'success' };
const mockGuarantee = {
  guaranteeId: 'GT2026001',
  customerId: '100100',
  customerName: 'Northwind Traders',
  amount: 50000,
};
const mockCountry = { countryId: 'CH', countryName: 'Switzerland' };

describe('toTitledRecords', () => {
  it('titles each record of the Temenos envelope and keeps the header', () => {
    const result = toTitledRecords({ header: mockHeader, body: [mockGuarantee] }, 'Guarantee');

    expect(result).toEqual({
      header: mockHeader,
      data: [{ title: 'Guarantee GT2026001 - Northwind Traders', record: mockGuarantee }],
    });
  });

  it('prefers an id or recordId field over other id fields', () => {
    const result = toTitledRecords(
      { body: [{ customerId: '100100', recordId: 'LIM.1' }] },
      'Limit',
    );

    expect(result.data?.[0]?.title).toBe('Limit LIM.1');
  });

  it('takes the next id field when the preferred one has no usable value', () => {
    const result = toTitledRecords(
      {
        body: [
          { id: null, recordId: 'GT2026001' },
          { id: ' ', guaranteeId: 'GT2026002' },
        ],
      },
      'Guarantee',
    );

    expect(result.data?.map(({ title }) => title)).toEqual([
      'Guarantee GT2026001',
      'Guarantee GT2026002',
    ]);
  });

  it('titles a record by its label and name when it has no id', () => {
    const result = toTitledRecords({ body: [{ subject: 'Card renewal' }] }, 'Secure message');

    expect(result.data?.[0]?.title).toBe('Secure message - Card renewal');
  });

  it('reads the name from a multi-valued Temenos field', () => {
    const record = { sectorId: '1001', descriptions: [{ description: 'Individuals' }] };

    const result = toTitledRecords({ body: [record] }, 'Sector');

    expect(result.data?.[0]?.title).toBe('Sector 1001 - Individuals');
  });

  it('reads the name from a later entry when the first entry has none', () => {
    const record = {
      sectorId: '1001',
      descriptions: [{ description: '' }, { description: 'Individuals' }],
    };

    const result = toTitledRecords({ body: [record] }, 'Sector');

    expect(result.data?.[0]?.title).toBe('Sector 1001 - Individuals');
  });

  it('formats a numeric id', () => {
    const result = toTitledRecords({ body: [{ id: 42 }] }, 'Category');

    expect(result.data?.[0]?.title).toBe('Category 42');
  });

  it('falls back to the label for a record with neither id nor name', () => {
    const result = toTitledRecords({ body: [{ amount: 10 }, 'raw'] }, 'Payment fee');

    expect(result.data).toEqual([
      { title: 'Payment fee', record: { amount: 10 } },
      { title: 'Payment fee', record: 'raw' },
    ]);
  });

  it('wraps a single body object as one record', () => {
    const result = toTitledRecords({ header: mockHeader, body: mockCountry }, 'Country');

    expect(result.data).toEqual([{ title: 'Country CH - Switzerland', record: mockCountry }]);
  });

  it('titles a bare array response', () => {
    const result = toTitledRecords([mockCountry], 'Country');

    expect(result).toEqual({ data: [{ title: 'Country CH - Switzerland', record: mockCountry }] });
  });

  it('returns no records for an empty response', () => {
    expect(toTitledRecords(undefined, 'Country')).toEqual({ data: [] });
  });
});
