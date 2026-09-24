import {
  BadRequestException,
  Inject,
  Injectable,
  ServiceUnavailableException,
} from '@nestjs/common';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

@Injectable()
export class EgressService {
  public constructor(@Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig) {}

  public approve(value: string): URL {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      throw new BadRequestException('invalid remote destination');
    }
    if (
      url.protocol !== 'https:' ||
      url.username ||
      url.password ||
      url.hash ||
      !this.config.egressAllowedHosts.includes(url.hostname)
    ) {
      throw new BadRequestException('remote destination is not approved');
    }
    return url;
  }

  public async fetch(url: string | URL, init: RequestInit, maxBytes = 65_536): Promise<Response> {
    const approved = this.approve(url.toString());
    try {
      const response = await fetch(approved, {
        ...init,
        redirect: 'error',
        signal: init.signal
          ? AbortSignal.any([init.signal, AbortSignal.timeout(this.config.dependencyTimeoutMs)])
          : AbortSignal.timeout(this.config.dependencyTimeoutMs),
      });
      const reader = response.body?.getReader();
      if (!reader) {
        return response;
      }
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          size += value.byteLength;
          if (size > maxBytes) {
            throw new Error('response too large');
          }
          chunks.push(value);
        }
      } finally {
        await reader.cancel();
      }
      const headers = new Headers(response.headers);
      headers.delete('content-encoding');
      headers.delete('content-length');
      return new Response(Buffer.concat(chunks), { status: response.status, headers });
    } catch {
      throw new ServiceUnavailableException('remote request failed');
    }
  }
}
