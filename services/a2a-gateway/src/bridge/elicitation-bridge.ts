import type { Part } from '@a2a-js/sdk';

const FREE_TEXT_FIELD = 'answer';
const MAX_QUESTION_LENGTH = 2_000;
const PRIMITIVE_TYPES = ['string', 'number', 'integer', 'boolean'];

export interface ElicitationRequest {
  message: string;
  schema: Record<string, unknown>;
  freeText: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Keeps only a flat object schema of primitive fields, the subset Unique's elicitation form
 * renders. Anything else from the remote agent becomes a single free-text answer.
 */
function formSchema(value: unknown): Record<string, unknown> | undefined {
  if (!isRecord(value) || value.type !== 'object' || !isRecord(value.properties)) {
    return undefined;
  }
  const properties: Record<string, unknown> = {};
  for (const [name, property] of Object.entries(value.properties).slice(0, 20)) {
    if (!isRecord(property) || !PRIMITIVE_TYPES.includes(String(property.type))) {
      return undefined;
    }
    properties[name.slice(0, 100)] = {
      type: property.type,
      ...(typeof property.title === 'string' ? { title: property.title.slice(0, 200) } : {}),
      ...(typeof property.description === 'string'
        ? { description: property.description.slice(0, 500) }
        : {}),
      ...(Array.isArray(property.enum) && property.enum.every((item) => typeof item === 'string')
        ? { enum: property.enum.slice(0, 50) }
        : {}),
    };
  }
  const required = Array.isArray(value.required)
    ? value.required.filter(
        (name): name is string => typeof name === 'string' && name in properties,
      )
    : [];
  return { type: 'object', properties, required };
}

/** Translates a remote `input-required` status message into a Unique FORM elicitation. */
export function elicitationRequest(parts: Part[]): ElicitationRequest {
  const question =
    parts
      .map((part) => (part.content?.$case === 'text' ? part.content.value : ''))
      .join('')
      .trim()
      .slice(0, MAX_QUESTION_LENGTH) || 'The external agent needs more information to continue.';
  const schema = parts
    .map((part) => (part.content?.$case === 'data' ? formSchema(part.content.value) : undefined))
    .find((candidate) => candidate !== undefined);
  if (schema) {
    return { message: question, schema, freeText: false };
  }
  return {
    message: question,
    schema: {
      type: 'object',
      properties: { [FREE_TEXT_FIELD]: { type: 'string', title: 'Answer' } },
      required: [FREE_TEXT_FIELD],
    },
    freeText: true,
  };
}

/** The follow-up parts answering the remote agent: free text as text, forms as structured data. */
export function answerParts(content: unknown, schema: Record<string, unknown> | undefined): Part[] {
  const answer = isRecord(content) ? content : {};
  const properties = isRecord(schema?.properties) ? Object.keys(schema.properties) : [];
  if (properties.length === 1 && properties[0] === FREE_TEXT_FIELD) {
    return [
      {
        content: { $case: 'text', value: String(answer[FREE_TEXT_FIELD] ?? '') },
        metadata: undefined,
        filename: '',
        mediaType: 'text/plain',
      },
    ];
  }
  return [
    {
      content: { $case: 'data', value: answer },
      metadata: undefined,
      filename: '',
      mediaType: 'application/json',
    },
  ];
}
