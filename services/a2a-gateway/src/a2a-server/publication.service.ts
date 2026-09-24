import type { AgentCard } from '@a2a-js/sdk';
import { ForbiddenException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { AuthorizationService } from '../auth/authorization.service.js';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { PublicationRepository } from '../drizzle/publication.repository.js';
import {
  publicationCardSchema,
  publicationSkillSchema,
} from '../management/publication-configuration.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';

export interface CatalogAgent {
  publicationId: string;
  name: string;
  description: string;
  cardUrl: string;
  agentUrl: string;
}

function agentUrl(baseUrl: URL, publicationId: string): URL {
  return new URL(
    `a2a/agents/${publicationId}`,
    baseUrl.toString().endsWith('/') ? baseUrl : `${baseUrl}/`,
  );
}

@Injectable()
export class PublicationService {
  public constructor(
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
    private readonly authorization: AuthorizationService,
    private readonly publications: PublicationRepository,
  ) {}

  public async getAgentCard(publicationId: string): Promise<AgentCard> {
    const publication = await this.publications.findEnabledById(publicationId);
    if (!publication) {
      throw new NotFoundException('publication not found');
    }
    const card = publicationCardSchema.safeParse(publication.cardOverrides);
    const skills = publicationSkillSchema.array().safeParse(publication.skills);
    if (!card.success || !skills.success) {
      throw new NotFoundException('publication not found');
    }
    const endpoint = agentUrl(this.config.publicBaseUrl, publication.id);
    return {
      name: card.data.name,
      description: card.data.description,
      documentationUrl: card.data.documentationUrl,
      iconUrl: card.data.iconUrl,
      provider: card.data.provider,
      supportedInterfaces: [
        {
          url: endpoint.toString(),
          protocolBinding: 'JSONRPC',
          protocolVersion: '1.0',
          tenant: '',
        },
      ],
      version: String(publication.version),
      capabilities: {
        streaming: true,
        pushNotifications: false,
        extendedAgentCard: true,
        extensions: [],
      },
      securitySchemes: {
        uniqueOidc: {
          scheme: {
            $case: 'openIdConnectSecurityScheme',
            value: {
              description: 'Unique user authentication',
              openIdConnectUrl: new URL(
                '.well-known/openid-configuration',
                this.config.zitadelIssuer.toString().endsWith('/')
                  ? this.config.zitadelIssuer
                  : `${this.config.zitadelIssuer}/`,
              ).toString(),
            },
          },
        },
      },
      securityRequirements: [{ schemes: { uniqueOidc: { list: [] } } }],
      defaultInputModes: ['text/plain', 'application/json'],
      defaultOutputModes: ['text/plain', 'application/json'],
      skills: skills.data.map((skill) => ({
        ...skill,
        inputModes: [],
        outputModes: [],
        securityRequirements: [],
      })),
      signatures: [],
    };
  }

  public async catalog(identity: RequestIdentity): Promise<CatalogAgent[]> {
    const publications = await this.publications.listEnabled(identity.companyId);
    const visible = await Promise.all(
      publications.map(async (publication): Promise<CatalogAgent | undefined> => {
        try {
          await this.authorization.useSpace(identity, publication.assistantId);
        } catch (error) {
          if (
            error instanceof ForbiddenException ||
            error instanceof NotFoundException ||
            (error instanceof UniqueInternalError &&
              ['NOT_FOUND', 'UNAUTHORIZED'].includes(error.code))
          ) {
            return undefined;
          }
          throw error;
        }
        const card = publicationCardSchema.safeParse(publication.cardOverrides);
        if (!card.success) {
          return undefined;
        }
        const endpoint = agentUrl(this.config.publicBaseUrl, publication.id);
        return {
          publicationId: publication.id,
          name: card.data.name,
          description: card.data.description,
          cardUrl: new URL(`${endpoint.toString()}/.well-known/agent-card.json`).toString(),
          agentUrl: endpoint.toString(),
        };
      }),
    );
    return visible.filter((agent): agent is CatalogAgent => agent !== undefined);
  }
}
