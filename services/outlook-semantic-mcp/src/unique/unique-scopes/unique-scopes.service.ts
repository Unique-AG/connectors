import { Injectable } from "@nestjs/common";
import { Scope } from "./fetch-or-create-outlook-emails-root-scope.command";
import { last, randomString } from "remeda";

@Injectable()
export class UniqueScopesService {
  public createScopesBasedOnPaths(
    paths: string[],
    opts: { includePermissions: boolean; inheritAccess: boolean } = {
      includePermissions: false,
      inheritAccess: true,
    },
  ): Promise<Scope[]> {
    return Promise.resolve(
      paths.map((path) => {
        return {
          id: path,
          name: last(path.split("/").filter((item) => item !== "")) ?? path,
          parentId: null,
          externalId: null,
          scopeAccess: [
            { entityId: randomString(20), entityType: "USER", type: "MANAGE" },
          ],
        };
      }),
    );
  }

  public updateScopeExternalId(
    scopeId: string,
    externalId: unknown,
  ): Promise<{ id: string; externalId: string | null }> {
    return Promise.resolve({
      id: randomString(20),
      externalId: `${externalId}`,
    });
  }

  public updateScopeParent(
    scopeId: string,
    newParentId: string,
  ): Promise<{ id: string; parentId: string | null }> {
    return Promise.resolve({
      id: scopeId,
      parentId: newParentId,
    });
  }

  public async deleteScope(
    scopeId: string,
    options: { recursive?: boolean } = {},
  ): Promise<void> {
    return Promise.resolve();
  }
}
