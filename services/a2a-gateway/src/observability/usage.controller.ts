import { TaskState } from '@a2a-js/sdk';
import { BadRequestException, Controller, Get, Query, Req, UseGuards } from '@nestjs/common';
import type { Request } from 'express';
import { z } from 'zod';
import { AuthorizationService } from '../auth/authorization.service.js';
import { KongIdentityGuard, requestIdentity } from '../auth/identity.guard.js';
import { UsageRepository } from '../drizzle/usage.repository.js';

const MAX_RANGE_DAYS = 93;

const range = z
  .object({ from: z.iso.datetime(), to: z.iso.datetime() })
  .transform(({ from, to }) => ({ from: new Date(from), to: new Date(to) }))
  .refine(
    ({ from, to }) => from < to && to.getTime() - from.getTime() <= MAX_RANGE_DAYS * 86_400_000,
  );

/**
 * Usage attribution for the company's own A2A traffic, e.g. to report or charge the optional
 * add-on. Counts, durations and bytes only; pricing and invoicing are out of scope.
 */
@Controller('management/usage')
@UseGuards(KongIdentityGuard)
export class UsageController {
  public constructor(
    private readonly authorization: AuthorizationService,
    private readonly usage: UsageRepository,
  ) {}

  @Get()
  public async get(@Req() request: Request, @Query() query: unknown) {
    const identity = requestIdentity(request);
    await this.authorization.manageConnections(identity);
    const parsed = range.safeParse(query);
    if (!parsed.success) {
      throw new BadRequestException(
        `from/to must be ISO datetimes at most ${MAX_RANGE_DAYS} days apart`,
      );
    }
    const { from, to } = parsed.data;
    const [outbound, inbound] = await Promise.all([
      this.usage.outbound(identity.companyId, from, to),
      this.usage.inbound(identity.companyId, from, to),
    ]);
    return {
      from: from.toISOString(),
      to: to.toISOString(),
      outbound,
      inbound: inbound.map((row) => ({ ...row, state: TaskState[Number(row.state)] ?? row.state })),
    };
  }
}
