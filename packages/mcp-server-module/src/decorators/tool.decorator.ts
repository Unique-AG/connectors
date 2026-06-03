import {
  Tool as SdkTool,
  ToolAnnotations as SdkToolAnnotations,
} from '@modelcontextprotocol/sdk/types.js';
import { SetMetadata } from '@nestjs/common';
import * as z from 'zod';
import { MCP_TOOL_METADATA_KEY } from './constants';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ZodSchema = z.ZodObject<any> | z.ZodDiscriminatedUnion<any>;

export interface ToolMetadata {
  name: string;
  title?: string;
  description: string;
  parameters: ZodSchema;
  outputSchema?: ZodSchema;
  annotations?: SdkToolAnnotations;
  _meta?: SdkTool['_meta'];
  icons?: SdkTool['icons'];
}

export interface ToolAnnotations extends SdkToolAnnotations {}

export interface ToolOptions {
  name?: string;
  title?: string;
  description?: string;
  parameters: ZodSchema;
  outputSchema?: ZodSchema;
  annotations?: ToolAnnotations;
  _meta?: SdkTool['_meta'];
  icons?: SdkTool['icons'];
}

/**
 * Decorator that marks a controller method as an MCP tool.
 * @param {Object} options - The options for the decorator
 * @param {string} options.name - The name of the tool
 * @param {string} options.description - The description of the tool
 * @param {ZodSchema} [options.parameters] - The parameters of the tool (ZodObject or ZodDiscriminatedUnion)
 * @param {ZodSchema} [options.outputSchema] - The output schema of the tool (ZodObject or ZodDiscriminatedUnion)
 * @param {ToolAnnotations} [options.annotations] - The annotations of the tool
 * @param {SdkTool['_meta']} [options._meta] - The metadata of the tool
 * @param {SdkTool['icons']} [options.icons] - The icons of the tool
 * @returns {MethodDecorator} - The decorator
 */
export const Tool = (options: ToolOptions) => {
  if (options.parameters === undefined) {
    options.parameters = z.object({});
  }

  return SetMetadata(MCP_TOOL_METADATA_KEY, options);
};
