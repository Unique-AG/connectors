import type { CanActivate, ExecutionContext } from '@nestjs/common';
import { Inject, Injectable, UnauthorizedException } from '@nestjs/common';
import type { Request } from 'express';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

const commonIdentityHeaders = ['x-user-id', 'x-company-id'] as const;

export interface RequestIdentity {
  companyId: string;
  userId: string;
  roles: string[];
}

export function requestIdentity(request: Request): RequestIdentity {
  const companyId = request.headers['x-company-id'];
  const userId = request.headers['x-user-id'];
  const roles = request.headers['x-user-roles'];
  if (
    typeof companyId !== 'string' ||
    !companyId.trim() ||
    typeof userId !== 'string' ||
    !userId.trim()
  ) {
    throw new UnauthorizedException('trusted identity headers are required');
  }
  return {
    companyId,
    userId,
    roles: typeof roles === 'string' ? roles.split(',').map((role) => role.trim()) : [],
  };
}

function applyDevelopmentIdentity(request: Request): void {
  const authorization = request.headers.authorization;
  const token =
    typeof authorization === 'string' ? authorization.match(/^Bearer (\S+)$/)?.[1] : null;
  if (!token) {
    throw new UnauthorizedException('bearer token is required');
  }
  try {
    const payload = JSON.parse(
      Buffer.from(token.split('.')[1] ?? '', 'base64url').toString('utf8'),
    ) as {
      sub?: unknown;
      'urn:zitadel:iam:user:resourceowner:id'?: unknown;
    };
    const companyId = payload['urn:zitadel:iam:user:resourceowner:id'];
    if (typeof payload.sub !== 'string' || typeof companyId !== 'string') {
      throw new Error('identity claims are missing');
    }
    request.headers['x-user-id'] = payload.sub;
    request.headers['x-company-id'] = companyId;
  } catch {
    throw new UnauthorizedException('valid development identity claims are required');
  }
}

function hasHeaders(request: Request, names: readonly string[]): boolean {
  return names.every((name) => {
    const value = request.headers[name];
    return typeof value === 'string' && value.trim().length > 0;
  });
}

abstract class IdentityGuard implements CanActivate {
  protected constructor(
    private readonly config: GatewayConfig,
    private readonly requiredHeaders: readonly string[],
  ) {}

  public canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<Request>();
    if (this.config.authMode === 'development') {
      if (!hasHeaders(request, this.requiredHeaders)) {
        applyDevelopmentIdentity(request);
      }
      return true;
    }

    if (!hasHeaders(request, this.requiredHeaders)) {
      throw new UnauthorizedException('trusted identity headers are required');
    }
    if (request.headers['x-service-id']) {
      throw new UnauthorizedException('service identities are not supported');
    }
    return true;
  }
}

@Injectable()
export class KongIdentityGuard extends IdentityGuard {
  public constructor(@Inject(GATEWAY_CONFIG) config: GatewayConfig) {
    super(config, [...commonIdentityHeaders, 'x-client-id']);
  }
}

@Injectable()
export class ClusterIdentityGuard extends IdentityGuard {
  public constructor(@Inject(GATEWAY_CONFIG) config: GatewayConfig) {
    super(config, commonIdentityHeaders);
  }
}
