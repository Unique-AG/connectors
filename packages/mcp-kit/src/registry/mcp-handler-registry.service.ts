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

/** Shared fields present on every registry entry regardless of MCP handler type. */
interface BaseRegistryEntry {
  /** Constructor of the NestJS provider class that owns the decorated method. */
  // biome-ignore lint/suspicious/noExplicitAny: NestJS class constructor reference
  classRef: new (...args: any[]) => unknown;
  /** Live provider instance resolved from the NestJS DI container. */
  instance: object;
  /** Name of the decorated method on the provider class. */
  methodName: string;
  /** Parameter index decorated with `@McpCtx()`, or `undefined` if absent. */
  ctxParamIndex: number | undefined;
}

/** Registry entry for a method decorated with `@Tool()`. */
export interface ToolRegistryEntry extends BaseRegistryEntry {
  type: 'tool';
  name: string;
  metadata: ToolMetadata;
}

/** Registry entry for a method decorated with `@Resource()`. */
export interface ResourceRegistryEntry extends BaseRegistryEntry {
  type: 'resource';
  name: string;
  metadata: ResourceMetadata;
}

/** Registry entry for a method decorated with `@Prompt()`. */
export interface PromptRegistryEntry extends BaseRegistryEntry {
  type: 'prompt';
  name: string;
  metadata: PromptMetadata;
}

/** Discriminated union of all MCP handler registry entries. */
export type RegistryEntry = ToolRegistryEntry | ResourceRegistryEntry | PromptRegistryEntry;

/**
 * Discovers and indexes every MCP-decorated method (`@Tool`, `@Resource`, `@Prompt`) across all
 * NestJS providers at application bootstrap, making them available for dispatch at runtime.
 */
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

  /** Returns all registered tool entries. */
  public getTools(): ToolRegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e): e is ToolRegistryEntry => e.type === 'tool'));
  }

  /** Looks up a tool by its registered name. */
  public findTool(name: string): ToolRegistryEntry | undefined {
    const entry = this.entries.get(`tool:${name}`);
    return entry?.type === 'tool' ? entry : undefined;
  }

  /** Returns all registered resource entries (both static and template). */
  public getResources(): ResourceRegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e): e is ResourceRegistryEntry => e.type === 'resource'));
  }

  /** Returns only resource entries with a fixed URI (no template variables). */
  public getStaticResources(): ResourceRegistryEntry[] {
    return pipe(this.getResources(), filter((e) => e.metadata.kind === 'static'));
  }

  /** Returns only resource entries whose URI contains template variables. */
  public getTemplateResources(): ResourceRegistryEntry[] {
    return pipe(this.getResources(), filter((e) => e.metadata.kind === 'template'));
  }

  /**
   * Resolves a concrete request URI to a resource entry and extracted path/query parameters.
   * Tries an exact key lookup first; if that misses, iterates template resources and applies
   * URI template matching (supports `{param}`, `{param*}` wildcard, and `{?query,params}`).
   */
  public findResourceByUri(uri: string): { entry: ResourceRegistryEntry; params: Record<string, string> } | undefined {
    const exactKey = `resource:${uri}`;
    const exact = this.entries.get(exactKey);
    if (exact?.type === 'resource') {
      return { entry: exact, params: {} };
    }

    for (const entry of this.getTemplateResources()) {
      const params = matchUriTemplate(entry.metadata.uri, uri, entry.metadata.queryParams);
      if (params !== undefined) {
        return { entry, params };
      }
    }

    return undefined;
  }

  /** Returns all registered prompt entries. */
  public getPrompts(): PromptRegistryEntry[] {
    return pipe(Array.from(this.entries.values()), filter((e): e is PromptRegistryEntry => e.type === 'prompt'));
  }

  /** Looks up a prompt by its registered name. */
  public findPrompt(name: string): PromptRegistryEntry | undefined {
    const entry = this.entries.get(`prompt:${name}`);
    return entry?.type === 'prompt' ? entry : undefined;
  }

  /** Returns every registered entry across all handler types. */
  public getAll(): RegistryEntry[] {
    return Array.from(this.entries.values());
  }
}
