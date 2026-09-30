import type { AgentCard } from '@a2a-js/sdk';
import { DefaultAgentCardResolver } from '@a2a-js/sdk/client';
import type { CredentialProfile } from './credential-profile.js';

export interface NegotiatedCapabilities {
  protocolVersion: '1.0';
  url: string;
  streaming: boolean;
  pushNotifications: boolean;
  extendedAgentCard: boolean;
  inputModes: string[];
  outputModes: string[];
  warnings: string[];
}

export class IncompatibleAgentError extends Error {}

const TEXT_MODES = ['text', 'text/plain'];

/** Parses a strict A2A 1.0 card; 0.3 cards are not translated. */
export function parseAgentCard(value: unknown): AgentCard {
  const card = new DefaultAgentCardResolver().normalizeAgentCard(value);
  if (
    typeof card !== 'object' ||
    card === null ||
    typeof card.name !== 'string' ||
    !card.name.trim() ||
    !Array.isArray(card.supportedInterfaces)
  ) {
    throw new IncompatibleAgentError('The agent card is not a valid A2A 1.0 agent card.');
  }
  return card;
}

/**
 * Decides whether Unique can talk to the agent and records what it may use. The JSON-RPC endpoint
 * must share the card's origin because the shared credential is bound to that origin.
 */
export function negotiate(
  card: AgentCard,
  cardUrl: URL,
  credentialType: CredentialProfile['type'],
): NegotiatedCapabilities {
  const jsonRpc = card.supportedInterfaces.find(
    (candidate) =>
      candidate.protocolBinding?.toUpperCase() === 'JSONRPC' && candidate.protocolVersion === '1.0',
  );
  if (!jsonRpc) {
    throw new IncompatibleAgentError(
      'The agent does not offer an A2A 1.0 JSON-RPC interface. REST, gRPC and 0.3 agents are not supported.',
    );
  }
  let endpoint: URL;
  try {
    endpoint = new URL(jsonRpc.url);
  } catch {
    throw new IncompatibleAgentError('The agent card contains an invalid JSON-RPC URL.');
  }
  if (endpoint.origin !== cardUrl.origin) {
    throw new IncompatibleAgentError(
      `The JSON-RPC endpoint (${endpoint.origin}) must be on the same origin as the agent card (${cardUrl.origin}).`,
    );
  }
  const inputModes = card.defaultInputModes ?? [];
  if (inputModes.length && !inputModes.some((mode) => TEXT_MODES.includes(mode))) {
    throw new IncompatibleAgentError('The agent does not accept text input.');
  }
  const warnings: string[] = [];
  const requiresAuthentication = (card.securityRequirements ?? []).length > 0;
  if (requiresAuthentication && credentialType === 'none') {
    warnings.push('The agent declares required authentication, but no credential is configured.');
  }
  if (jsonRpc.tenant) {
    warnings.push('The agent uses a tenant; requests are sent with its default tenant.');
  }
  return {
    protocolVersion: '1.0',
    url: endpoint.toString(),
    streaming: card.capabilities?.streaming === true,
    pushNotifications: card.capabilities?.pushNotifications === true,
    extendedAgentCard: card.capabilities?.extendedAgentCard === true,
    inputModes,
    outputModes: card.defaultOutputModes ?? [],
    warnings,
  };
}

/** Identity and skills of the agent as shown to Space Admins; never includes credentials. */
export function cardPreview(card: AgentCard) {
  return {
    name: card.name,
    description: card.description ?? '',
    version: card.version ?? '',
    provider: card.provider?.organization ?? '',
    documentationUrl: card.documentationUrl ?? '',
    skills: (card.skills ?? []).map((skill) => ({
      id: skill.id,
      name: skill.name,
      description: skill.description ?? '',
    })),
  };
}
