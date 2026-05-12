import { ResourceTemplate as SdkResourceTemplate } from '@modelcontextprotocol/sdk/types.js';
import { SetMetadata } from '@nestjs/common';
import { MCP_RESOURCE_TEMPLATE_METADATA_KEY } from './constants';

export interface ResourceTemplateOptions {
  // https://modelcontextprotocol.io/docs/concepts/resources#resource-templates
  uriTemplate: string; // URI template following RFC 6570
  name?: string; // Human-readable name
  description?: string; // Optional description
  mimeType?: string; // Optional MIME type
  icons?: SdkResourceTemplate['icons'];
}

export interface ResourceTemplateMetadata {
  uriTemplate: string; // URI template following RFC 6570
  name: string; // Human-readable name
  description?: string; // Optional description
  mimeType?: string; // Optional MIME type
  icons?: SdkResourceTemplate['icons'];
}

/**
 * Decorator that marks a controller method as an MCP resource.
 * @param {Object} options - The options for the decorator
 * @param {string} options.name - The name of the resource
 * @param {string} options.uriTemplate - The URI template of the resource
 * @returns {MethodDecorator} - The decorator
 */
export const ResourceTemplate = (options: ResourceTemplateOptions) => {
  return SetMetadata(MCP_RESOURCE_TEMPLATE_METADATA_KEY, options);
};
