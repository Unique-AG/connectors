import type { CanActivate, ExecutionContext } from '@nestjs/common';
import { Inject, Injectable, UnauthorizedException } from '@nestjs/common';
import type { Request } from 'express';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

const commonIdentityHeaders = ['x-user-id', 'x-company-id', 'x-user-roles'] as const;

export interface RequestIdentity {
  companyId: string;
  userId: string;
  roles: string[];
}

export function requestIdentity(request: Request): RequestIdentity {
  const companyId = request.headers['x-company-id'];
  const userId = request.headers['x-user-id'];
  const roles = request.headers['x-user-roles'];
  if (typeof companyId !== 'string' || typeof userId !== 'string') {
    throw new UnauthorizedException('trusted identity headers are required');
  }
  return {
    companyId,
    userId,
    roles: typeof roles === 'string' ? roles.split(',').map((role) => role.trim()) : [],
  };
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
    if (this.config.authMode === 'development') {
      return true;
    }

    const request = context.switchToHttp().getRequest<Request>();
    if (!hasHeaders(request, this.requiredHeaders)) {
      throw new UnauthorizedException('trusted identity headers are required');
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
