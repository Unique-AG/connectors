export const UNIQUE_API_MODULE_OPTIONS = Symbol('UNIQUE_API_MODULE_OPTIONS');

export const UNIQUE_API_CLIENT_FACTORY = Symbol('UNIQUE_API_CLIENT_FACTORY');

export const UNIQUE_API_CLIENT_REGISTRY = Symbol('UNIQUE_API_CLIENT_REGISTRY');

export function getUniqueApiClientToken(name: string): string {
  return `UNIQUE_API_CLIENT_${name}`;
}
