import { omit } from 'remeda';
import { SearchCondition } from './semantic-search-conditions.dto';

export function filterConditionsForMailbox(
  conditions: SearchCondition[] | undefined,
  branchEmail: string,
): Omit<SearchCondition, 'mailbox'>[] {
  if (!conditions?.length) {
    return [];
  }

  return conditions
    .filter((c) => c.mailbox === undefined || c.mailbox === branchEmail)
    .map((c) => omit(c, ['mailbox']));
}
