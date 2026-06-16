import { Prompt as SdkPrompt } from '@modelcontextprotocol/sdk/types.js';
import { SetMetadata } from '@nestjs/common';
import * as z from 'zod';
import { MCP_PROMPT_METADATA_KEY } from './constants';

export interface PromptMetadata {
  name: string;
  title?: string;
  description: string;
  parameters?: z.ZodObject;
  _meta?: SdkPrompt['_meta'];
  icons?: SdkPrompt['icons'];
}

export interface PromptOptions {
  name?: string;
  title?: string;
  description: string;
  parameters?: z.ZodObject;
  _meta?: SdkPrompt['_meta'];
  icons?: SdkPrompt['icons'];
}

/**
 * Decorator that marks a controller method as an MCP prompt.
 * @param {Object} options - The options for the decorator
 * @param {string} options.name - The name of the prompt
 * @param {string} options.description - The description of the prompt
 * @param {z.ZodObject} [options.parameters] - The parameters of the prompt
 * @param {SdkPrompt['_meta']} [options._meta] - The metadata of the prompt
 * @param {SdkPrompt['icons']} [options.icons] - The icons of the prompt
 * @returns {MethodDecorator} - The decorator
 */
export const Prompt = (options: PromptOptions) => {
  return SetMetadata(MCP_PROMPT_METADATA_KEY, options);
};
