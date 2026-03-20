import type { SimpleUser, UserWithCompany } from './users.types';

export interface UniqueUsersFacade {
  listAll(): Promise<SimpleUser[]>;
  getCurrentId(): Promise<string>;
  findByEmail(email: string): Promise<UserWithCompany | null>;
}
