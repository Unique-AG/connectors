import { User } from 'oidc-client-ts';

const API_BASE_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:3000';

/**
 * Get the current user's access token from OIDC storage
 */
function getAccessToken(): string | null {
  const oidcKey = Object.keys(localStorage).find((key) => key.startsWith('oidc.user:'));
  if (!oidcKey) return null;

  const oidcStorage = localStorage.getItem(oidcKey);
  if (!oidcStorage) return null;

  try {
    const user = User.fromStorageString(oidcStorage);
    return user.access_token;
  } catch {
    return null;
  }
}

/**
 * Make an authenticated API request
 */
export async function apiRequest<T = any>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getAccessToken();

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
      ...options.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      // Token expired or invalid - trigger re-authentication
      window.location.href = '/login';
    }
    throw new Error(`API request failed: ${response.statusText}`);
  }

  return response.json();
}

/**
 * API service for MCP endpoints
 */
export const mcpApi = {
  /**
   * Send a command to the MCP server
   */
  async sendCommand(command: any) {
    return apiRequest('/mcp', {
      method: 'POST',
      body: JSON.stringify(command),
    });
  },

  /**
   * Get MCP server info
   */
  async getServerInfo() {
    return apiRequest('/');
  },

  /**
   * Get user's Microsoft Graph data
   */
  async getGraphData(endpoint: string) {
    return apiRequest(`/graph${endpoint}`);
  },
};
