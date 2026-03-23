import { MCP_RESOURCE_METADATA } from '../constants';
import type { McpIcon } from '../types';
import { invariant } from '../errors/defect.js';

export interface ResourceOptions {
  uri: string;
  name?: string;
  description?: string;
  mimeType?: string;
  icons?: McpIcon[];
  meta?: Record<string, unknown>;
  version?: string | number;
  annotations?: {
    readOnlyHint?: boolean;
    idempotentHint?: boolean;
  };
}

export interface ResourceMetadata {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
  kind: 'static' | 'template';
  templateParams: string[];
  queryParams: string[];
  icons?: McpIcon[];
  meta?: Record<string, unknown>;
  version?: string | number;
  annotations?: {
    readOnlyHint?: boolean;
    idempotentHint?: boolean;
  };
  methodName: string;
}

export function Resource(options: ResourceOptions): MethodDecorator {
  return (target, propertyKey, descriptor) => {
    const methodName = String(propertyKey);
    const { templateParams, queryParams } = parseUriTemplate(options.uri);
    const kind: 'static' | 'template' =
      templateParams.length > 0 || queryParams.length > 0 ? 'template' : 'static';

    const metadata: ResourceMetadata = {
      uri: options.uri,
      name: options.name !== undefined ? options.name : methodName,
      description: options.description,
      mimeType: options.mimeType,
      kind,
      templateParams,
      queryParams,
      icons: options.icons,
      meta: options.meta,
      version: options.version,
      annotations: options.annotations,
      methodName,
    };

    const method = descriptor.value;
    invariant(method !== undefined, '@Resource() must be applied to a method');
    Reflect.defineMetadata(MCP_RESOURCE_METADATA, metadata, method);
  };
}

function parseUriTemplate(uri: string): { templateParams: string[]; queryParams: string[] } {
  const queryParams = [...uri.matchAll(/\{\?([^}]+)\}/g)].flatMap((m) =>
    m[1].split(',').map((p) => p.trim()),
  );

  const uriWithoutQuery = uri.replace(/\{\?[^}]+\}/g, '');

  const templateParams = [
    ...[...uriWithoutQuery.matchAll(/\{(\w+)\*\}/g)].map((m) => `${m[1]}*`),
    ...[...uriWithoutQuery.matchAll(/\{(\w+)\}/g)].map((m) => m[1]),
  ];

  return { templateParams, queryParams };
}
