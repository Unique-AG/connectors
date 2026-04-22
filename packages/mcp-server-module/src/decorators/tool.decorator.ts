import {
  Tool as SdkTool,
  ToolAnnotations as SdkToolAnnotations,
} from '@modelcontextprotocol/sdk/types.js';
import { SetMetadata } from '@nestjs/common';
import * as z from 'zod';
import { MCP_TOOL_METADATA_KEY } from './constants';

export interface ToolMetadata {
  name: string;
  title?: string;
  description: string;
  parameters: z.ZodObject;
  outputSchema?: z.ZodObject;
  annotations?: SdkToolAnnotations;
  _meta?: SdkTool['_meta'];
}

export interface ToolAnnotations extends SdkToolAnnotations {}

export interface ToolOptions {
  name?: string;
  title?: string;
  description?: string;
  parameters: z.ZodObject;
  outputSchema?: z.ZodObject;
  annotations?: ToolAnnotations;
  _meta?: SdkTool['_meta'];
}

/**
 * Decorator that marks a controller method as an MCP tool.
 * @param {Object} options - The options for the decorator
 * @param {string} options.name - The name of the tool
 * @param {string} options.description - The description of the tool
 * @param {z.ZodObject} [options.parameters] - The parameters of the tool
 * @param {z.ZodObject} [options.outputSchema] - The output schema of the tool
 * @param {ToolAnnotations} [options.annotations] - The annotations of the tool
 * @param {SdkTool['_meta']} [options._meta] - The metadata of the tool
 * @returns {MethodDecorator} - The decorator
 */
export const Tool = (options: ToolOptions) => {
  if (options.parameters === undefined) {
    options.parameters = z.object({});
  }

  return SetMetadata(MCP_TOOL_METADATA_KEY, options);
};
