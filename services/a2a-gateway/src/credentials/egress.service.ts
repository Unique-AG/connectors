import { type LookupAddress, lookup } from 'node:dns';
import {
  BadRequestException,
  Inject,
  Injectable,
  type OnApplicationShutdown,
  ServiceUnavailableException,
} from '@nestjs/common';
import ipaddr from 'ipaddr.js';
import { Agent, fetch as undiciFetch } from 'undici';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

export class EgressBlockedError extends Error {}

function isPublicAddress(address: string): boolean {
  if (!ipaddr.isValid(address)) {
    return false;
  }
  const parsed = ipaddr.process(address);
  return parsed.range() === 'unicast';
}

export function boundedBody(body: ReadableStream<Uint8Array>, maxBytes: number) {
  let size = 0;
  return body.pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        size += chunk.byteLength;
        if (size > maxBytes) {
          controller.error(new Error('response too large'));
          return;
        }
        controller.enqueue(chunk);
      },
    }),
  );
}

/**
 * Single egress path for every remote request (cards, JSON-RPC, OAuth, files, webhooks):
 * HTTPS to operator-approved hosts only, no redirects, bounded time and size, and a DNS lookup
 * that is pinned to the connection so a public name cannot rebind to a private address.
 */
@Injectable()
export class EgressService implements OnApplicationShutdown {
  private readonly dispatcher: Agent;

  public constructor(@Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig) {
    const allowPrivate = config.egressAllowInsecure;
    this.dispatcher = new Agent({
      connect: {
        rejectUnauthorized: true,
        lookup: (hostname, options, callback) => {
          lookup(hostname, { ...options, all: true }, (error, addresses: LookupAddress[]) => {
            if (error) {
              callback(error, []);
              return;
            }
            if (!allowPrivate && addresses.some(({ address }) => !isPublicAddress(address))) {
              callback(new EgressBlockedError('destination resolves to a non-public address'), []);
              return;
            }
            callback(null, addresses);
          });
        },
      },
      headersTimeout: config.dependencyTimeoutMs,
      connectTimeout: config.dependencyTimeoutMs,
    });
  }

  public approve(value: string): URL {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      throw new BadRequestException('invalid remote destination');
    }
    const secure =
      url.protocol === 'https:' || (this.config.egressAllowInsecure && url.protocol === 'http:');
    if (
      !secure ||
      url.username ||
      url.password ||
      url.hash ||
      !this.config.egressAllowedHosts.includes(url.hostname)
    ) {
      throw new BadRequestException('remote destination is not approved');
    }
    const literal = url.hostname.replace(/^\[|\]$/g, '');
    if (!this.config.egressAllowInsecure && ipaddr.isValid(literal) && !isPublicAddress(literal)) {
      throw new BadRequestException('remote destination is not approved');
    }
    return url;
  }

  /**
   * Client-registered webhook URLs: HTTPS on 443 to an operator-approved host that resolves to a
   * public address (checked again at connect time). No gateway credential is ever attached.
   */
  public approveWebhook(value: string): URL {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      throw new BadRequestException('invalid webhook URL');
    }
    const secure =
      url.protocol === 'https:' || (this.config.egressAllowInsecure && url.protocol === 'http:');
    const literal = url.hostname.replace(/^\[|\]$/g, '');
    if (
      !secure ||
      url.username ||
      url.password ||
      url.hash ||
      (url.port !== '' && !this.config.egressAllowInsecure) ||
      !this.config.pushAllowedHosts.includes(url.hostname) ||
      (!this.config.egressAllowInsecure && ipaddr.isValid(literal) && !isPublicAddress(literal))
    ) {
      throw new BadRequestException('webhook URL is not allowed');
    }
    return url;
  }

  public async postWebhook(url: string, init: RequestInit): Promise<Response> {
    return this.send(this.approveWebhook(url), { ...init, method: 'POST' }, 16_384, 10_000);
  }

  /** Buffers the whole bounded response; for JSON documents and OAuth token responses. */
  public async fetch(url: string | URL, init: RequestInit, maxBytes = 65_536): Promise<Response> {
    const response = await this.stream(url, init, maxBytes, this.config.dependencyTimeoutMs);
    try {
      const body = Buffer.from(await response.arrayBuffer());
      return new Response(body, { status: response.status, headers: response.headers });
    } catch {
      throw new ServiceUnavailableException('remote request failed');
    }
  }

  /**
   * Streams a bounded response (SSE, file downloads). The body errors once `maxBytes` is exceeded
   * or `timeoutMs` elapses; callers own the consumption and cancellation of the body.
   */
  public async stream(
    url: string | URL,
    init: RequestInit,
    maxBytes: number,
    timeoutMs = this.config.streamTimeoutMs,
  ): Promise<Response> {
    return this.send(this.approve(url.toString()), init, maxBytes, timeoutMs);
  }

  private async send(
    approved: URL,
    init: RequestInit,
    maxBytes: number,
    timeoutMs: number,
  ): Promise<Response> {
    const timeout = AbortSignal.timeout(timeoutMs);
    const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
    let response: Awaited<ReturnType<typeof undiciFetch>>;
    try {
      response = await undiciFetch(approved, {
        method: init.method,
        headers: init.headers as Record<string, string> | Headers | undefined,
        body: init.body as string | Uint8Array | undefined,
        redirect: 'error',
        signal,
        dispatcher: this.dispatcher,
      });
    } catch (error) {
      throw new ServiceUnavailableException('remote request failed', { cause: error });
    }
    const headers = new Headers(response.headers as unknown as Headers);
    headers.delete('content-encoding');
    headers.delete('content-length');
    const body = response.body
      ? boundedBody(response.body as unknown as ReadableStream<Uint8Array>, maxBytes)
      : null;
    return new Response(body, { status: response.status, headers });
  }

  public async onApplicationShutdown(): Promise<void> {
    await this.dispatcher.close();
  }
}
