export const UNIQUE_API_MODULE_OPTIONS = Symbol('UNIQUE_API_MODULE_OPTIONS');

export const UNIQUE_API_CLIENT_FACTORY = Symbol('UNIQUE_API_CLIENT_FACTORY');

export const UNIQUE_API_CLIENT_REGISTRY = Symbol('UNIQUE_API_CLIENT_REGISTRY');

export const UNIQUE_API_METER = Symbol('UNIQUE_API_METER');

export const UNIQUE_API_METRICS = Symbol('UNIQUE_API_METRICS');

export function getUniqueApiClientToken(name: string): string {
  return `UNIQUE_API_CLIENT_${name}`;
}
