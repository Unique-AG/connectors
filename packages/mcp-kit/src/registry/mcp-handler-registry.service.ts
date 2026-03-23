import { Injectable, Logger, OnApplicationBootstrap } from '@nestjs/common';
import { DiscoveryService, MetadataScanner } from '@nestjs/core';
import { filter, isFunction, isObjectType, pipe } from 'remeda';
import { MCP_PROMPT_METADATA, MCP_RESOURCE_METADATA, MCP_TOOL_METADATA } from '../constants';
import { invariant } from '../errors/defect.js';
import type { PromptMetadata } from '../decorators/prompt.decorator';
import type { ResourceMetadata } from '../decorators/resource.decorator';
import type { ToolMetadata } from '../decorators/tool.decorator';
import { scanMethodParams } from './param-scanner';
import { matchUriTemplate } from './uri-template-matcher';

interface BaseRegistryEntry {
  // biome-ignore lint/suspicious/noExplicitAny: NestJS class constructor reference
  classRef: new (...args: any[]) => unknown;
  instance: object;
  methodName: string;
  ctxParamIndex: number | undefined;
}

export interface ToolRegistryEntry extends BaseRegistryEntry {
  type: 'tool';
  name: string;
  metadata: ToolMetadata;
}

export interface ResourceRegistryEntry extends BaseRegistryEntry {
  type: 'resource';
  name: string;
  metadata: ResourceMetadata;
}

export interface PromptRegistryEntry extends BaseRegistryEntry {
  type: 'prompt';
  name: string;
  metadata: PromptMetadata;
}

export type RegistryEntry = ToolRegistryEntry | ResourceRegistryEntry | PromptRegistryEntry;

@Injectable()
export class McpHandlerRegistry implements OnApplicationBootstrap {
  private readonly logger = new Logger(McpHandlerRegistry.name);
  private readonly entries = new Map<string, RegistryEntry>();

  public constructor(
    private readonly discoveryService: DiscoveryService,
    private readonly metadataScanner: MetadataScanner,
  ) {}

  private getTypeName(metatype: Function | undefined): string {
    return metatype !== undefined ? metatype.name : 'unknown';
  }

  public onApplicationBootstrap(): void {
    const providers = this.discoveryService.getProviders();

    for (const wrapper of providers) {
      const { instance } = wrapper;
      if (!isObjectType(instance)) continue;

      const prototype = Object.getPrototypeOf(instance) as object;

      this.metadataScanner.scanFromPrototype(
        instance as Record<string, unknown>,
        prototype,
        (methodName: string) => {
          const methodRef = (instance as Record<string, unknown>)[methodName];
          if (!isFunction(methodRef)) return;

          this.tryRegisterTool(instance as object, prototype, methodName, methodRef, wrapper.metatype);
          this.tryRegisterResource(instance as object, prototype, methodName, methodRef, wrapper.metatype);
          this.tryRegisterPrompt(instance as object, prototype, methodName, methodRef, wrapper.metatype);
        },
      );
    }

    this.logger.log(
      `Registered ${this.getTools().length} tools, ${this.getStaticResources().length + this.getTemplateResources().length} resources, ${this.getPrompts().length} prompts`,
    );
  }

  private tryRegisterTool(
    instance: object,
    prototype: object,
    methodName: string,
    // biome-ignore lint/suspicious/noExplicitAny: method reference from prototype scan
    methodRef: (...args: any[]) => unknown,
    metatype: Function | undefined,
  ): void {
    const metadata: ToolMetadata | undefined = Reflect.getMetadata(MCP_TOOL_METADATA, methodRef);
    if (!metadata) return;

    const key = `tool:${metadata.name}`;
    if (this.entries.has(key)) {
      const existing = this.entries.get(key);
      invariant(existing !== undefined, `Registry entry for key "${key}" must exist after has() check`);
      throw new Error(
        `Duplicate tool name "${metadata.name}" registered in ${this.getTypeName(metatype)} and ${existing.classRef.name}. Tool names must be unique.`,
      );
    }

    const { ctxParamIndex } = scanMethodParams(prototype, methodName);

    this.entries.set(key, {
      type: 'tool',
      name: metadata.name,
      metadata,
      classRef: metatype as new (...args: any[]) => unknown,
      instance,
      methodName,
      ctxParamIndex,
    });
  }

  private tryRegisterResource(
    instance: object,
    prototype: object,
    methodName: string,
    // biome-ignore lint/suspicious/noExplicitAny: method reference from prototype scan
    methodRef: (...args: any[]) => unknown,
    metatype: Function | undefined,
  ): void {
    const metadata: ResourceMetadata | undefined = Reflect.getMetadata(MCP_RESOURCE_METADATA, methodRef);
    if (!metadata) return;

    const key = `resource:${metadata.uri}`;
    if (this.entries.has(key)) {
      const existing = this.entries.get(key);
      invariant(existing !== undefined, `Registry entry for key "${key}" must exist after has() check`);
      throw new Error(
        `Duplicate resource URI "${metadata.uri}" registered in ${this.getTypeName(metatype)} and ${existing.classRef.name}. Resource URIs must be unique.`,
      );
    }

    const { ctxParamIndex } = scanMethodParams(prototype, methodName);

    this.entries.set(key, {
      type: 'resource',
      name: metadata.name,
      metadata,
      classRef: metatype as new (...args: any[]) => unknown,
      instance,
      methodName,
      ctxParamIndex,
    });
  }

  private tryRegisterPrompt(
    instance: object,
    prototype: object,
    methodName: string,
    // biome-ignore lint/suspicious/noExplicitAny: method reference from prototype scan
    methodRef: (...args: any[]) => unknown,
    metatype: Function | undefined,
  ): void {
    const metadata: PromptMetadata | undefined = Reflect.getMetadata(MCP_PROMPT_METADATA, methodRef);
    if (!metadata) return;

    const key = `prompt:${metadata.name}`;
    if (this.entries.has(key)) {
      const existing = this.entries.get(key);
      invariant(existing !== undefined, `Registry entry for key "${key}" must exist after has() check`);
      throw new Error(
        `Duplicate prompt name "${metadata.name}" registered in ${this.getTypeName(metatype)} and ${existing.classRef.name}. Prompt names must be unique.`,
      );
    }

    const { ctxParamIndex } = scanMethodParams(prototype, methodName);

    this.entries.set(key, {
      type: 'prompt',
      name: metadata.name,
      metadata,
      classRef: metatype as new (...args: any[]) => unknown,
      instance,
      methodName,
      ctxParamIndex,
    });
  }

  public getTools(): ToolRegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e): e is ToolRegistryEntry => e.type === 'tool'));
  }

  public findTool(name: string): ToolRegistryEntry | undefined {
    const entry = this.entries.get(`tool:${name}`);
    return entry?.type === 'tool' ? entry : undefined;
  }

  public getResources(): ResourceRegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e): e is ResourceRegistryEntry => e.type === 'resource'));
  }

  public getStaticResources(): ResourceRegistryEntry[] {
    return pipe(this.getResources(), filter((e) => e.metadata.kind === 'static'));
  }

  public getTemplateResources(): ResourceRegistryEntry[] {
    return pipe(this.getResources(), filter((e) => e.metadata.kind === 'template'));
  }

  public findResourceByUri(uri: string): { entry: ResourceRegistryEntry; params: Record<string, string> } | undefined {
    const exactKey = `resource:${uri}`;
    const exact = this.entries.get(exactKey);
    if (exact?.type === 'resource') {
      return { entry: exact, params: {} };
    }

    for (const entry of this.getTemplateResources()) {
      const params = matchUriTemplate(entry.metadata.uri, uri, entry.metadata.templateParams, entry.metadata.queryParams);
      if (params !== undefined) {
        return { entry, params };
      }
    }

    return undefined;
  }

  public getPrompts(): PromptRegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e): e is PromptRegistryEntry => e.type === 'prompt'));
  }

  public findPrompt(name: string): PromptRegistryEntry | undefined {
    const entry = this.entries.get(`prompt:${name}`);
    return entry?.type === 'prompt' ? entry : undefined;
  }

  public getAll(): RegistryEntry[] {
    return Array.from(this.entries.values());
  }
}
