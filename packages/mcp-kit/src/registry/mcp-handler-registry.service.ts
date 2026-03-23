import { Injectable, Logger, OnApplicationBootstrap } from '@nestjs/common';
import { DiscoveryService, MetadataScanner } from '@nestjs/core';
import { filter, pipe } from 'remeda';
import { MCP_PROMPT_METADATA, MCP_RESOURCE_METADATA, MCP_TOOL_METADATA } from '../constants';
import type { PromptMetadata } from '../decorators/prompt.decorator';
import type { ResourceMetadata } from '../decorators/resource.decorator';
import type { ToolMetadata } from '../decorators/tool.decorator';
import { scanMethodParams } from './param-scanner';
import { matchUriTemplate } from './uri-template-matcher';

export interface RegistryEntry {
  type: 'tool' | 'resource' | 'prompt';
  name: string;
  metadata: ToolMetadata | ResourceMetadata | PromptMetadata;
  // biome-ignore lint/suspicious/noExplicitAny: NestJS class constructor reference
  classRef: new (...args: any[]) => unknown;
  instance: object;
  methodName: string;
  ctxParamIndex: number | undefined;
}

@Injectable()
export class McpHandlerRegistry implements OnApplicationBootstrap {
  private readonly logger = new Logger(McpHandlerRegistry.name);
  private readonly entries = new Map<string, RegistryEntry>();

  public constructor(
    private readonly discoveryService: DiscoveryService,
    private readonly metadataScanner: MetadataScanner,
  ) {}

  public onApplicationBootstrap(): void {
    const providers = this.discoveryService.getProviders();

    for (const wrapper of providers) {
      const { instance } = wrapper;
      if (!instance || typeof instance !== 'object') continue;

      const prototype = Object.getPrototypeOf(instance) as object;

      this.metadataScanner.scanFromPrototype(
        instance as Record<string, unknown>,
        prototype,
        (methodName: string) => {
          const methodRef = (instance as Record<string, unknown>)[methodName];
          if (typeof methodRef !== 'function') return;

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
    // biome-ignore lint/suspicious/noExplicitAny: NestJS metatype
    metatype: any,
  ): void {
    const metadata: ToolMetadata | undefined = Reflect.getMetadata(MCP_TOOL_METADATA, methodRef);
    if (!metadata) return;

    const key = `tool:${metadata.name}`;
    if (this.entries.has(key)) {
      const existing = this.entries.get(key)!;
      throw new Error(
        `Duplicate tool name "${metadata.name}" registered in ${metatype?.name ?? 'unknown'} and ${existing.classRef?.name ?? 'unknown'}. Tool names must be unique.`,
      );
    }

    const { ctxParamIndex } = scanMethodParams(prototype, methodName);

    this.entries.set(key, {
      type: 'tool',
      name: metadata.name,
      metadata,
      classRef: metatype,
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
    // biome-ignore lint/suspicious/noExplicitAny: NestJS metatype
    metatype: any,
  ): void {
    const metadata: ResourceMetadata | undefined = Reflect.getMetadata(MCP_RESOURCE_METADATA, methodRef);
    if (!metadata) return;

    const key = `resource:${metadata.uri}`;
    if (this.entries.has(key)) {
      const existing = this.entries.get(key)!;
      throw new Error(
        `Duplicate resource URI "${metadata.uri}" registered in ${metatype?.name ?? 'unknown'} and ${existing.classRef?.name ?? 'unknown'}. Resource URIs must be unique.`,
      );
    }

    const { ctxParamIndex } = scanMethodParams(prototype, methodName);

    this.entries.set(key, {
      type: 'resource',
      name: metadata.name,
      metadata,
      classRef: metatype,
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
    // biome-ignore lint/suspicious/noExplicitAny: NestJS metatype
    metatype: any,
  ): void {
    const metadata: PromptMetadata | undefined = Reflect.getMetadata(MCP_PROMPT_METADATA, methodRef);
    if (!metadata) return;

    const key = `prompt:${metadata.name}`;
    if (this.entries.has(key)) {
      const existing = this.entries.get(key)!;
      throw new Error(
        `Duplicate prompt name "${metadata.name}" registered in ${metatype?.name ?? 'unknown'} and ${existing.classRef?.name ?? 'unknown'}. Prompt names must be unique.`,
      );
    }

    const { ctxParamIndex } = scanMethodParams(prototype, methodName);

    this.entries.set(key, {
      type: 'prompt',
      name: metadata.name,
      metadata,
      classRef: metatype,
      instance,
      methodName,
      ctxParamIndex,
    });
  }

  public getTools(): RegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e) => e.type === 'tool'));
  }

  public findTool(name: string): RegistryEntry | undefined {
    return this.entries.get(`tool:${name}`);
  }

  public getResources(): RegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e) => e.type === 'resource'));
  }

  public getStaticResources(): RegistryEntry[] {
    return pipe(this.getResources(), filter((e) => (e.metadata as ResourceMetadata).kind === 'static'));
  }

  public getTemplateResources(): RegistryEntry[] {
    return pipe(this.getResources(), filter((e) => (e.metadata as ResourceMetadata).kind === 'template'));
  }

  public findResourceByUri(uri: string): { entry: RegistryEntry; params: Record<string, string> } | undefined {
    const exactKey = `resource:${uri}`;
    const exact = this.entries.get(exactKey);
    if (exact) {
      return { entry: exact, params: {} };
    }

    for (const entry of this.getTemplateResources()) {
      const metadata = entry.metadata as ResourceMetadata;
      const params = matchUriTemplate(metadata.uri, uri, metadata.templateParams, metadata.queryParams);
      if (params !== undefined) {
        return { entry, params };
      }
    }

    return undefined;
  }

  public getPrompts(): RegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e) => e.type === 'prompt'));
  }

  public findPrompt(name: string): RegistryEntry | undefined {
    return this.entries.get(`prompt:${name}`);
  }

  public getAll(): RegistryEntry[] {
    return Array.from(this.entries.values());
  }
}
