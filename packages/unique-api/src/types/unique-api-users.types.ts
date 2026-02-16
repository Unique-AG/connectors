import type { SimpleUser } from '../users/users.types';

export interface UniqueApiUsers {
  listAll(): Promise<SimpleUser[]>;
  getCurrentId(): Promise<string>;
}
