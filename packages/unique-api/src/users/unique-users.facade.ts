import type { SimpleUser } from './users.types';

export interface UniqueUsersFacade {
  listAll(): Promise<SimpleUser[]>;
  getCurrentId(): Promise<string>;
}
