import { Attributes, Histogram } from '@opentelemetry/api';
import { isFunction } from 'remeda';

type Callback<T> = () => Promise<T>;
type ArgumentsFn<T> = (params: T) => Attributes;

export const recordInHistogram = async <T>({
  histogram,
  attributes: attributs,
  fn,
}: {
  histogram: Histogram;
  attributes: Attributes | ArgumentsFn<T>;
  fn: Callback<T>;
}): Promise<T> => {
  let result: { type: 'success'; data: T } | { type: 'error'; err: unknown };
  const pageStart = Date.now();
  try {
    const data = await fn();
    result = { type: 'success', data };
  } catch (err) {
    result = { type: 'error', err };
  }
  const pageDurationMs = Date.now() - pageStart;

  let attributesData: Attributes = {
    __outcome: result.type,
  };
  if (!isFunction(attributs)) {
    attributesData = { ...attributesData, ...attributs };
  } else if (result.type === 'success') {
    attributesData = { ...attributesData, ...attributs(result.data) };
  }
  histogram.record(pageDurationMs / 1000, attributesData);
  if (result.type === 'error') {
    throw result.err;
  }
  return result.data;
};
