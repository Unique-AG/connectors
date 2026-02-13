import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { UniqueConfigNamespaced } from '~/config';

@Injectable()
export class UniqueApiClient {
  private readonly logger = new Logger(UniqueApiClient.name);

  public constructor(private readonly config: ConfigService<UniqueConfigNamespaced, true>) {}

  public getBaseUrl(): string {
    return this.config.get('unique.apiBaseUrl', { infer: true });
  }

  public getAuthHeaders(): Record<string, string> {
    const uniqueConfig = this.config.get('unique', { infer: true });
    return {
      'x-api-version': uniqueConfig.apiVersion,
      ...uniqueConfig.serviceExtraHeaders,
    };
  }

  public createEndpoint(path: string): URL {
    return new URL(path, this.getBaseUrl());
  }

  public async get<T>(path: string, params?: Record<string, string>): Promise<T> {
    const endpoint = this.createEndpoint(path);
    if (params) {
      const searchParams = new URLSearchParams(params);
      endpoint.search = searchParams.toString();
    }

    this.logger.debug({ endpoint: endpoint.pathname }, `GET ${path}`);

    const response = await fetch(endpoint, {
      method: 'GET',
      headers: this.getAuthHeaders(),
    });

    if (!response.ok) {
      this.logger.error(
        { status: response.status, endpoint: endpoint.pathname },
        `GET ${path} failed`,
      );
      throw new Error(`Unique API GET ${path} failed: ${response.status}`);
    }

    return response.json() as Promise<T>;
  }

  public async post<T>(path: string, body: unknown): Promise<T> {
    const endpoint = this.createEndpoint(path);

    this.logger.debug({ endpoint: endpoint.pathname }, `POST ${path}`);

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders(),
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      this.logger.error(
        { status: response.status, endpoint: endpoint.pathname },
        `POST ${path} failed`,
      );
      throw new Error(`Unique API POST ${path} failed: ${response.status}`);
    }

    return response.json() as Promise<T>;
  }

  public async patch<T>(path: string, body: unknown): Promise<T> {
    const endpoint = this.createEndpoint(path);

    this.logger.debug({ endpoint: endpoint.pathname }, `PATCH ${path}`);

    const response = await fetch(endpoint, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders(),
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      this.logger.error(
        { status: response.status, endpoint: endpoint.pathname },
        `PATCH ${path} failed`,
      );
      throw new Error(`Unique API PATCH ${path} failed: ${response.status}`);
    }

    return response.json() as Promise<T>;
  }
}
