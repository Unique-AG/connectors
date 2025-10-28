export const AuthenticationScope = {
  GRAPH: 'graph',
  SHAREPOINT_REST: 'sharepoint-rest',
} as const;

export type AuthenticationScope = (typeof AuthenticationScope)[keyof typeof AuthenticationScope];

export interface TokenAcquisitionResult {
  token: string;
  expiresAt: number;
}
