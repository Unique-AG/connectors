export interface OAuthClient {
  client_id: string;
  client_secret?: string;
  client_name: string;
  client_description?: string;
  logo_uri?: string;
  client_uri?: string;
  developer_name?: string;
  developer_email?: string;
  redirect_uris: string[];
  grant_types: string[];
  response_types: string[];
  token_endpoint_auth_method: string;
  created_at: Date;
  updated_at: Date;
}

/**
 * RFC 7591 compliant client registration response.
 * @see https://datatracker.ietf.org/doc/html/rfc7591#section-3.2.1
 */
export interface ClientRegistrationResponse {
  client_id: string;
  client_secret?: string;
  client_id_issued_at: number;
  client_secret_expires_at?: number;
  client_name: string;
  client_description?: string;
  logo_uri?: string;
  client_uri?: string;
  developer_name?: string;
  developer_email?: string;
  redirect_uris: string[];
  grant_types: string[];
  response_types: string[];
  token_endpoint_auth_method: string;
}

export interface AuthorizationCode {
  code: string;
  user_id: string;
  client_id: string;
  redirect_uri: string;
  code_challenge: string;
  code_challenge_method: string;
  resource?: string;
  scope?: string;
  expires_at: number;
  user_profile_id: string;
}
