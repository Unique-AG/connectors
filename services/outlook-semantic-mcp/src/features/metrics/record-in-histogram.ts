import { Attributes, Histogram } from '@opentelemetry/api';

type Callback<T> = () => Promise<T>;
export type ArgumentsFn<T> = (params: T) => Attributes;

export const recordInHistogram = async <T>({
  histogram,
  attributes,
  successAtrributes,
  errorAttributtes,
  fn,
}: {
  histogram: Histogram;
  // static attributes always passed to the histogram
  attributes?: Attributes;
  // callback function to create attributes related to success results
  successAtrributes?: ArgumentsFn<T>;
  // callback function to create attributes related to error results
  errorAttributtes?: ArgumentsFn<unknown>;
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
    ...attributes,
    funtionRunResult: result.type,
  };

  if (result.type === 'success') {
    attributesData = { ...successAtrributes?.(result.data), ...attributesData };
  } else {
    attributesData = { ...errorAttributtes?.(result.err), ...attributesData };
  }
  histogram.record(pageDurationMs / 1000, attributesData);
  if (result.type === 'error') {
    throw result.err;
  }
  return result.data;
};
