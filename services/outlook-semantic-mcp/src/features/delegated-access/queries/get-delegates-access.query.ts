import { Injectable } from '@nestjs/common';
import { DelegatedAccessInfoDto } from './delegated-access-info.dto';
import { GetDirectoryDelegatedAccessQuery } from './get-directory-delegated-access.query';
import { GetFullDelegatedAccessQuery } from './get-full-delegated-access.query';

@Injectable()
export class GetDelegatedAccessQuery {
  public constructor(
    private getDirectoryDelegatedAccessQuery: GetDirectoryDelegatedAccessQuery,
    private getFullDelegatedAccessQuery: GetFullDelegatedAccessQuery,
  ) {}

  public async run(userProfileId: string): Promise<DelegatedAccessInfoDto[]> {
    const directoryDelegatedAccessQuery =
      await this.getDirectoryDelegatedAccessQuery.run(userProfileId);
    const fullDelegatedAccessQuery = await this.getFullDelegatedAccessQuery.run(userProfileId);

    return [...directoryDelegatedAccessQuery, ...fullDelegatedAccessQuery];
  }
}
