import { TokenAcquisitionResult } from '../types';

export interface AuthStrategy {
  acquireNewToken(scopes: string[]): Promise<TokenAcquisitionResult>;
}
