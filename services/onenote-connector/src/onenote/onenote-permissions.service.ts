import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import pLimit from 'p-limit';
import type { UniqueConfigNamespaced } from '~/config';
import {
  type PublicScopeAccessSchema,
  ScopeAccessEntityType,
  ScopeAccessType,
} from '~/unique/unique.dtos';
import { UniqueUserService } from '~/unique/unique-user.service';
import type { DrivePermission } from './onenote.types';
import { OneNoteGraphService } from './onenote-graph.service';

@Injectable()
export class OneNotePermissionsService {
  private readonly logger = new Logger(OneNotePermissionsService.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly graphService: OneNoteGraphService,
    private readonly userService: UniqueUserService,
  ) {}

  @Span()
  public async resolveNotebookAccesses(
    client: Client,
    permissions: DrivePermission[],
    ownerEmail?: string,
  ): Promise<PublicScopeAccessSchema[]> {
    const concurrency = this.config.get('unique.userFetchConcurrency', { infer: true });
    const limit = pLimit(concurrency);
    const accesses: PublicScopeAccessSchema[] = [];
    const resolvedEmails = new Set<string>();

    const emails = this.extractEmailsFromPermissions(permissions);

    if (ownerEmail) {
      emails.add(ownerEmail);
    }

    const resolvePromises = [...emails].map((email) =>
      limit(async () => {
        const user = await this.userService.findUserByEmail(email);
        if (user && !resolvedEmails.has(email)) {
          resolvedEmails.add(email);

          if (email === ownerEmail) {
            accesses.push(
              {
                entityId: user.id,
                entityType: ScopeAccessEntityType.User,
                type: ScopeAccessType.Read,
              },
              {
                entityId: user.id,
                entityType: ScopeAccessEntityType.User,
                type: ScopeAccessType.Write,
              },
              {
                entityId: user.id,
                entityType: ScopeAccessEntityType.User,
                type: ScopeAccessType.Manage,
              },
            );
          } else {
            accesses.push({
              entityId: user.id,
              entityType: ScopeAccessEntityType.User,
              type: ScopeAccessType.Read,
            });
          }
        }
      }),
    );

    const groupIds = this.extractGroupIdsFromPermissions(permissions);
    for (const groupId of groupIds) {
      resolvePromises.push(
        limit(async () => {
          const members = await this.graphService.getGroupMembers(client, groupId);
          for (const member of members) {
            const memberEmail = member.mail ?? member.userPrincipalName;
            if (memberEmail && !resolvedEmails.has(memberEmail)) {
              const user = await this.userService.findUserByEmail(memberEmail);
              if (user) {
                resolvedEmails.add(memberEmail);
                accesses.push({
                  entityId: user.id,
                  entityType: ScopeAccessEntityType.User,
                  type: ScopeAccessType.Read,
                });
              }
            }
          }
        }),
      );
    }

    await Promise.all(resolvePromises);

    this.logger.debug(
      { resolvedUsers: resolvedEmails.size, totalAccesses: accesses.length },
      'Resolved notebook access permissions',
    );

    return accesses;
  }

  private extractEmailsFromPermissions(permissions: DrivePermission[]): Set<string> {
    const emails = new Set<string>();

    for (const perm of permissions) {
      if (perm.grantedToV2?.user?.email) {
        emails.add(perm.grantedToV2.user.email);
      }

      if (perm.grantedToIdentitiesV2) {
        for (const identity of perm.grantedToIdentitiesV2) {
          if (identity.user?.email) {
            emails.add(identity.user.email);
          }
        }
      }
    }

    return emails;
  }

  private extractGroupIdsFromPermissions(permissions: DrivePermission[]): Set<string> {
    const groupIds = new Set<string>();

    for (const perm of permissions) {
      if (perm.grantedToV2?.group?.id) {
        groupIds.add(perm.grantedToV2.group.id);
      }

      if (perm.grantedToIdentitiesV2) {
        for (const identity of perm.grantedToIdentitiesV2) {
          if (identity.group?.id) {
            groupIds.add(identity.group.id);
          }
        }
      }
    }

    return groupIds;
  }
}
