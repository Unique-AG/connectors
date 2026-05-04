import { isNullish, omit } from 'remeda';
import { SearchCondition } from './semantic-search-conditions.dto';

export function filterConditionsForMailbox(
  conditions: SearchCondition[] | undefined,
  branchEmail: string,
): Omit<SearchCondition, 'mailbox'>[] {
  if (!conditions?.length) {
    return [];
  }

  return conditions
    .filter((condition) => isNullish(condition.mailbox) || condition.mailbox === branchEmail)
    .map((condition) => omit(condition, ['mailbox']));
}
