import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { AppConfig, AppSettings } from '../app-settings.enum';
import type { Workflow } from './@generated/n8n-api';

export interface GetWorkflowsParams {
  active?: boolean;
  tags?: string;
  name?: string;
  projectId?: string;
  excludePinnedData?: boolean;
  limit?: number;
  cursor?: string;
}

export interface GetWorkflowParams {
  excludePinnedData?: boolean;
}

export interface GetExecutionsParams {
  includeData?: boolean;
  status?: 'canceled' | 'error' | 'running' | 'success' | 'waiting';
  workflowId?: string;
  projectId?: string;
  limit?: number;
  cursor?: string;
}

export interface GetExecutionParams {
  includeData?: boolean;
}

export interface ActivateWorkflowBody {
  versionId?: string;
  name?: string;
  description?: string;
}

export interface RetryExecutionBody {
  loadWorkflow?: boolean;
}

@Injectable()
export class N8nApiService {
  private readonly logger = new Logger(N8nApiService.name);
  private readonly baseUrl: string;
  private readonly apiKey: string;

  public constructor(configService: ConfigService<AppConfig, true>) {
    this.baseUrl = configService.get(AppSettings.N8N_API_URL);
    this.apiKey = configService.get(AppSettings.N8N_API_KEY);
  }

  private getRequestInit(options?: RequestInit): RequestInit {
    return {
      ...options,
      headers: {
        'X-N8N-API-KEY': this.apiKey,
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    };
  }

  private buildUrl(path: string, params?: Record<string, unknown>): string {
    const url = new URL(`${this.baseUrl}/api/v1${path}`);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          url.searchParams.append(key, String(value));
        }
      }
    }
    return url.toString();
  }

  private async request<T>(
    path: string,
    options?: RequestInit & { params?: Record<string, unknown> },
  ): Promise<T> {
    const { params, ...requestOptions } = options || {};
    const url = this.buildUrl(path, params);
    const init = this.getRequestInit(requestOptions);

    this.logger.debug({ msg: 'Making n8n API request', url, method: init.method || 'GET' });

    const response = await fetch(url, init);
    const body = [204, 205, 304].includes(response.status) ? null : await response.text();
    const data = body ? JSON.parse(body) : {};

    if (!response.ok) {
      this.logger.error({ msg: 'n8n API request failed', status: response.status, data });
      throw new Error(`n8n API error: ${response.status} - ${JSON.stringify(data)}`);
    }

    return data as T;
  }

  public async getWorkflows(params?: GetWorkflowsParams) {
    return this.request<{ data: Workflow[]; nextCursor?: string | null }>('/workflows', {
      method: 'GET',
      params: params as Record<string, unknown>,
    });
  }

  public async getWorkflow(id: string, params?: GetWorkflowParams) {
    return this.request<Workflow>(`/workflows/${id}`, {
      method: 'GET',
      params: params as Record<string, unknown>,
    });
  }

  public async createWorkflow(workflow: Workflow) {
    return this.request<Workflow>('/workflows', {
      method: 'POST',
      body: JSON.stringify(workflow),
    });
  }

  public async updateWorkflow(id: string, workflow: Workflow) {
    return this.request<Workflow>(`/workflows/${id}`, {
      method: 'PUT',
      body: JSON.stringify(workflow),
    });
  }

  public async deleteWorkflow(id: string) {
    return this.request<Workflow>(`/workflows/${id}`, {
      method: 'DELETE',
    });
  }

  public async activateWorkflow(id: string, body?: ActivateWorkflowBody) {
    return this.request<Workflow>(`/workflows/${id}/activate`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    });
  }

  public async deactivateWorkflow(id: string) {
    return this.request<Workflow>(`/workflows/${id}/deactivate`, {
      method: 'POST',
    });
  }

  public async getWorkflowTags(id: string) {
    return this.request<Array<{ id?: string; name: string }>>(`/workflows/${id}/tags`, {
      method: 'GET',
    });
  }

  public async updateWorkflowTags(id: string, tagIds: Array<{ id: string }>) {
    return this.request<Array<{ id?: string; name: string }>>(`/workflows/${id}/tags`, {
      method: 'PUT',
      body: JSON.stringify(tagIds),
    });
  }

  public async getExecutions(params?: GetExecutionsParams) {
    return this.request<{ data: unknown[]; nextCursor?: string | null }>('/executions', {
      method: 'GET',
      params: params as Record<string, unknown>,
    });
  }

  public async getExecution(id: number, params?: GetExecutionParams) {
    return this.request<unknown>(`/executions/${id}`, {
      method: 'GET',
      params: params as Record<string, unknown>,
    });
  }

  public async deleteExecution(id: number) {
    return this.request<unknown>(`/executions/${id}`, {
      method: 'DELETE',
    });
  }

  public async retryExecution(id: number, body?: RetryExecutionBody) {
    return this.request<unknown>(`/executions/${id}/retry`, {
      method: 'POST',
      body: JSON.stringify(body || {}),
    });
  }
}
