import {
  BadRequestException,
  Body,
  ConflictException,
  Controller,
  Delete,
  Get,
  NotFoundException,
  Param,
  Patch,
  Post,
  Query,
} from '@nestjs/common';
import { ZodError, z } from 'zod';
import { DemoRepository } from './data/demo.repository';
import { isResourceName, RESOURCE_NAMES, RecordInput, ResourceName } from './data/demo-record';
import { parseRawEmail } from './data/email-parser';

const RecordInputSchema = z.object({
  id: z.string().trim().min(1).optional(),
  relationshipId: z.string().trim().min(1).nullable().optional(),
  data: z.record(z.string(), z.unknown()),
});

const RawEmailSchema = z.object({
  rawEmail: z.string().min(1),
  relationshipId: z.string().trim().min(1).nullable().optional(),
});

const parseBody = <T>(schema: z.ZodType<T>, value: unknown): T => {
  try {
    return schema.parse(value);
  } catch (error) {
    if (error instanceof ZodError) {
      throw new BadRequestException(z.prettifyError(error));
    }
    throw error;
  }
};

const parseResource = (value: string): ResourceName => {
  if (!isResourceName(value)) {
    throw new NotFoundException(`Unknown resource "${value}".`);
  }
  return value;
};

@Controller('api')
export class ApiController {
  public constructor(private readonly repository: DemoRepository) {}

  @Get()
  public getApiInfo() {
    return {
      snapshotDate: this.repository.snapshotDate,
      resources: Object.fromEntries(
        RESOURCE_NAMES.map((resource) => [resource, this.repository.list(resource).length]),
      ),
    };
  }

  @Get('relationship-details/:id')
  public getRelationshipDetails(@Param('id') id: string) {
    const relationship = this.repository.get('relationships', id);
    if (!relationship) {
      throw new NotFoundException(`Relationship "${id}" was not found.`);
    }

    return {
      relationship,
      related: Object.fromEntries(
        RESOURCE_NAMES.filter((resource) => resource !== 'relationships').map((resource) => [
          resource,
          this.repository.list(resource, id),
        ]),
      ),
    };
  }

  @Post('messages/import')
  public importMessage(@Body() body: unknown) {
    const input = parseBody(RawEmailSchema, body);
    try {
      const data = parseRawEmail(input.rawEmail);
      return this.repository.create('messages', {
        relationshipId: input.relationshipId,
        data: { ...data, sourceFile: null, imported: true },
      });
    } catch (error) {
      throw new BadRequestException(error instanceof Error ? error.message : 'Invalid email.');
    }
  }

  @Post('reset')
  public reset() {
    const resources = this.repository.reset();
    return {
      snapshotDate: this.repository.snapshotDate,
      resources,
    };
  }

  @Get(':resource')
  public list(
    @Param('resource') resourceValue: string,
    @Query('relationshipId') relationshipId?: string,
  ) {
    return {
      items: this.repository.list(parseResource(resourceValue), relationshipId),
    };
  }

  @Get(':resource/:id')
  public get(@Param('resource') resourceValue: string, @Param('id') id: string) {
    const resource = parseResource(resourceValue);
    const record = this.repository.get(resource, id);
    if (!record) {
      throw new NotFoundException(`${resource} record "${id}" was not found.`);
    }
    return record;
  }

  @Post(':resource')
  public create(@Param('resource') resourceValue: string, @Body() body: unknown) {
    const resource = parseResource(resourceValue);
    const input = parseBody<RecordInput>(RecordInputSchema, body);
    try {
      return this.repository.create(resource, input);
    } catch (error) {
      if (error instanceof Error && error.message.includes('UNIQUE constraint failed')) {
        throw new ConflictException(`${resource} record "${input.id}" already exists.`);
      }
      throw error;
    }
  }

  @Patch(':resource/:id')
  public update(
    @Param('resource') resourceValue: string,
    @Param('id') id: string,
    @Body() body: unknown,
  ) {
    const resource = parseResource(resourceValue);
    const input = parseBody<RecordInput>(RecordInputSchema, body);
    const updated = this.repository.update(resource, id, input);
    if (!updated) {
      throw new NotFoundException(`${resource} record "${id}" was not found.`);
    }
    return updated;
  }

  @Delete(':resource/:id')
  public delete(@Param('resource') resourceValue: string, @Param('id') id: string) {
    const resource = parseResource(resourceValue);
    if (!this.repository.delete(resource, id)) {
      throw new NotFoundException(`${resource} record "${id}" was not found.`);
    }
    return { deleted: true, id };
  }
}
