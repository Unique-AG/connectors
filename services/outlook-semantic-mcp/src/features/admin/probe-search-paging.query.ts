import assert from 'node:assert';
import { type MetadataFilter, type UniqueApiClient, UniqueQLOperator } from '@unique-ag/unique-api';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { UserProfile } from '~/db';
import { SearchCursorRepository } from '~/features/content/search/cursors/search-cursor.repository';
import { toRelativeGraphUrl } from '~/features/content/search/ms-graph-kql-search-emails.query';
import { SearchBackend } from '~/features/content/search/search-results.types';
import { ListMailboxesAndDirectoriesQuery } from '~/features/delegated-access/queries/list-mailboxes-and-directories.query';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import {
  getRootScopeExternalId,
  getRootScopeExternalIdForUser,
} from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { isMicrosoftGraphBackend } from '~/utils/backend-config.utils';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { sanitizeKqlQuery } from '~/utils/sanitize-kql-query';

// Matches almost every email, so the chain is long enough to reach the 1,000-result ceiling.
const PROBE_KQL = 'kind:email';
const PROBE_SELECT = 'id,sentDateTime,receivedDateTime';
const FIRST_PAGE_SIZE = 5;
const CEILING_PAGE_SIZE = 250;
const CEILING_MAX_PAGES = 8;
const GRAPH_SEARCH_CEILING = 1000;
const UNIQUE_PROBE_PROMPT = 'email';
const UNIQUE_PAGE_SIZE = 5;

type CheckResult = 'pass' | 'fail' | 'inconclusive';

interface Check {
  name: string;
  result: CheckResult;
  detail: string;
}

interface Fixture {
  url: string;
  status: number;
  headers?: Record<string, string>;
  body: unknown;
}

interface CeilingWalkPage {
  status: number;
  count: number;
  hasNextLink: boolean;
}

type GraphClient = ReturnType<GraphClientFactory['createClientForUser']>;

const subResponseSchema = z.object({
  id: z.string(),
  status: z.number(),
  headers: z.record(z.string(), z.string()).optional(),
  body: z.unknown(),
});

const batchResponseSchema = z.object({ responses: z.array(subResponseSchema) });

const messagePageSchema = z.object({
  value: z.array(
    z.object({
      id: z.string(),
      sentDateTime: z.string().nullish(),
      receivedDateTime: z.string().nullish(),
    }),
  ),
  '@odata.nextLink': z.string().optional(),
});

type MessagePage = z.infer<typeof messagePageSchema>;

const parsePage = (fixture: Fixture): MessagePage | undefined => {
  if (fixture.status !== 200) {
    return undefined;
  }
  const parsed = messagePageSchema.safeParse(fixture.body);
  return parsed.success ? parsed.data : undefined;
};

const isSortedDescending = (values: Array<string | null | undefined>): boolean =>
  values.every((value, i) => i === 0 || (values[i - 1] ?? '') >= (value ?? ''));

const MAX_ERROR_BODY_LENGTH = 1000;

const describeError = (error: unknown): string => {
  if (!(error instanceof Error)) {
    return String(error);
  }
  const body = 'body' in error ? error.body : undefined;
  return body === undefined
    ? error.message
    : `${error.message}: ${String(body).slice(0, MAX_ERROR_BODY_LENGTH)}`;
};

const fromBase64 = (value: string) => Buffer.from(value, 'base64').toString();

// Observed shape: base64("1&" + base64(base64("i=<guid>&s=<offset>"))). Undocumented, probe use only.
const decodeSkiptoken = (nextLink: string): { i: string; s: string } | undefined => {
  const token = URL.parse(nextLink)?.searchParams.get('$skiptoken');
  const inner = token ? fromBase64(token).split('&')[1] : undefined;
  if (!inner) {
    return undefined;
  }
  const params = new URLSearchParams(fromBase64(fromBase64(inner)));
  const i = params.get('i');
  const s = params.get('s');
  return i && s ? { i, s } : undefined;
};

const graphErrorCode = (body: unknown): string | undefined => {
  const parsed = z.object({ error: z.object({ code: z.string() }) }).safeParse(body);
  return parsed.success ? parsed.data.error.code : undefined;
};

/**
 * Checks the Microsoft Graph and Unique search behaviour the search paging relies on, in the
 * signed-in user's own mailbox (the ceiling walk also tries full-access delegated mailboxes).
 * Every Graph call goes through `$batch`, as production does.
 */
@Injectable()
export class ProbeSearchPagingQuery {
  public constructor(
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly searchCursorRepository: SearchCursorRepository,
    private readonly listMailboxesAndDirectoriesQuery: ListMailboxesAndDirectoriesQuery,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID) {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfile.id);
    const mailbox = userProfile.email;
    const searchQuery = `$search=${encodeURIComponent(sanitizeKqlQuery(PROBE_KQL))}&$select=${PROBE_SELECT}`;
    const messagesUrl = `/users/${mailbox}/messages?${searchQuery}&$top=${FIRST_PAGE_SIZE}`;

    const [messagesFixture, folderFixture] = await this.batchGet(client, [
      messagesUrl,
      `/users/${mailbox}/mailFolders/inbox/messages?${searchQuery}&$top=${FIRST_PAGE_SIZE}`,
    ]);
    assert.ok(messagesFixture && folderFixture, 'Microsoft Graph $batch dropped a sub-response');
    const firstPage = parsePage(messagesFixture);
    const nextLink = firstPage?.['@odata.nextLink'];
    const relativeNextLink = nextLink ? toRelativeGraphUrl(nextLink) : undefined;
    const folderFirstPage = parsePage(folderFixture);
    const folderNextLink = folderFirstPage?.['@odata.nextLink'];
    const relativeFolderNextLink = folderNextLink ? toRelativeGraphUrl(folderNextLink) : undefined;

    const secondPage = relativeNextLink
      ? await this.probeSecondPage(
          client,
          'graphRelativeNextLinkInBatch',
          firstPage,
          relativeNextLink,
        )
      : undefined;
    const folderSecondPage = relativeFolderNextLink
      ? await this.probeSecondPage(
          client,
          'graphRelativeMailFolderNextLinkInBatch',
          folderFirstPage,
          relativeFolderNextLink,
        )
      : undefined;
    const tampered =
      nextLink && firstPage
        ? await this.probeTamperedNextLink(client, nextLink, firstPage)
        : undefined;
    const skiptoken = nextLink
      ? await this.probeSkiptokenShape(client, messagesUrl, nextLink, secondPage?.nextLink)
      : undefined;
    const ceiling = await this.probeCeiling(client, userProfile, searchQuery);
    const staleLinkCursorId =
      firstPage && relativeNextLink
        ? await this.storeStaleLinkCursor(userProfile, relativeNextLink, firstPage)
        : undefined;
    const uniqueChecks = isMicrosoftGraphBackend()
      ? [
          {
            name: 'uniquePageIndex',
            result: 'inconclusive' as const,
            detail: 'Skipped: Unique search is not used in Microsoft Graph-only mode.',
          },
        ]
      : await this.probeUniquePaging(userProfile);

    return {
      mailbox,
      kqlQuery: PROBE_KQL,
      checks: [
        this.checkNextLink('graphNextLinkOnMessages', messagesFixture),
        this.checkNextLink('graphNextLinkOnMailFolder', folderFixture),
        this.checkNewestFirst(firstPage),
        this.checkNextLinkIsV1(nextLink, relativeNextLink),
        this.checkNextLinkIsV1(
          folderNextLink,
          relativeFolderNextLink,
          'graphMailFolderNextLinkUnderV1',
        ),
        ...(secondPage ? [secondPage.check] : []),
        ...(folderSecondPage ? [folderSecondPage.check] : []),
        ...(tampered ? [tampered.check] : []),
        ...(skiptoken ? [skiptoken] : []),
        ceiling.check,
        ...uniqueChecks,
      ],
      ceilingWalk: ceiling.walks,
      staleNextLink: staleLinkCursorId
        ? {
            cursorId: staleLinkCursorId,
            expectedFirstReceivedDateTimeUtc: secondPage?.firstReceivedDateTime,
            howToUse:
              'Call fetch_next_search_pages with this cursorId after some hours or days. ' +
              'If the first result was received at `expectedFirstReceivedDateTimeUtc` (shown in the mailbox timezone), the old link still works. `expired` means Graph rejected the link or restarted it from the first page.',
          }
        : undefined,
      fixtures: {
        firstPage: messagesFixture,
        mailFolderFirstPage: folderFixture,
        secondPageViaBatch: secondPage?.fixture,
        mailFolderSecondPageViaBatch: folderSecondPage?.fixture,
        tamperedNextLink: tampered?.fixture,
      },
    };
  }

  private async batchGet(client: GraphClient, urls: string[]): Promise<Fixture[]> {
    const raw = await client.api('$batch').post({
      requests: urls.map((url, i) => ({ id: `${i}`, method: 'GET', url })),
    });
    const { responses } = batchResponseSchema.parse(raw);
    return urls.flatMap((url, i) => {
      const response = responses.find(({ id }) => id === `${i}`);
      return response
        ? [{ url, status: response.status, headers: response.headers, body: response.body }]
        : [];
    });
  }

  private checkNextLink(name: string, fixture: Fixture): Check {
    const page = parsePage(fixture);
    if (!page) {
      return {
        name,
        result: 'fail',
        detail: `Graph returned ${fixture.status} (${graphErrorCode(fixture.body) ?? 'no error code'}).`,
      };
    }
    if (page['@odata.nextLink']) {
      return { name, result: 'pass', detail: 'Graph returned an @odata.nextLink.' };
    }
    return page.value.length < FIRST_PAGE_SIZE
      ? {
          name,
          result: 'inconclusive',
          detail: `Only ${page.value.length} results matched, so there is no next page to link to.`,
        }
      : {
          name,
          result: 'fail',
          detail: `A full page of ${page.value.length} results came back without an @odata.nextLink.`,
        };
  }

  private checkNewestFirst(page: MessagePage | undefined): Check {
    const name = 'graphSortedNewestFirst';
    if (!page || page.value.length < 2) {
      return { name, result: 'inconclusive', detail: 'Fewer than 2 results to compare.' };
    }
    const bySent = isSortedDescending(page.value.map(({ sentDateTime }) => sentDateTime));
    const byReceived = isSortedDescending(
      page.value.map(({ receivedDateTime }) => receivedDateTime),
    );
    return {
      name,
      result: bySent ? 'pass' : 'fail',
      detail: `Sorted by sentDateTime descending: ${bySent}. By receivedDateTime descending: ${byReceived}.`,
    };
  }

  private checkNextLinkIsV1(
    nextLink: string | undefined,
    relativeNextLink: string | undefined,
    name = 'graphNextLinkUnderV1',
  ): Check {
    if (!nextLink) {
      return { name, result: 'inconclusive', detail: 'No @odata.nextLink to inspect.' };
    }
    const url = URL.parse(nextLink);
    const shape = url
      ? `${url.origin}${url.pathname.replace(/\/users\/[^/]+/, '/users/{mailbox}')} with query parameters ${Array.from(url.searchParams.keys()).join(', ')}`
      : 'not a valid URL';
    return {
      name,
      result: relativeNextLink ? 'pass' : 'fail',
      detail: `nextLink is ${shape}.`,
    };
  }

  private async probeSecondPage(
    client: GraphClient,
    name: string,
    firstPage: MessagePage | undefined,
    relativeNextLink: string,
  ): Promise<{
    check: Check;
    fixture?: Fixture;
    nextLink?: string;
    firstReceivedDateTime?: string;
  }> {
    try {
      const [fixture] = await this.batchGet(client, [relativeNextLink]);
      assert.ok(fixture, 'Microsoft Graph $batch dropped a sub-response');
      const secondPage = parsePage(fixture);
      if (!secondPage) {
        return {
          check: {
            name,
            result: 'fail',
            detail: `Graph returned ${fixture.status} (${graphErrorCode(fixture.body) ?? 'no error code'}) for the relative nextLink.`,
          },
          fixture,
        };
      }
      const firstIds = new Set(firstPage?.value.map(({ id }) => id));
      const overlap = secondPage.value.filter(({ id }) => firstIds.has(id)).length;
      const lastSentOnFirstPage = firstPage?.value.at(-1)?.sentDateTime ?? '';
      const firstSentOnSecondPage = secondPage.value[0]?.sentDateTime ?? '';
      const continuesOrder = firstSentOnSecondPage <= lastSentOnFirstPage;
      return {
        check: {
          name,
          result: overlap === 0 && continuesOrder ? 'pass' : 'fail',
          detail: `Second page: ${secondPage.value.length} results, ${overlap} repeated from the first page, continues the sent-date order: ${continuesOrder}.`,
        },
        fixture,
        nextLink: secondPage['@odata.nextLink'],
        firstReceivedDateTime: secondPage.value[0]?.receivedDateTime ?? undefined,
      };
    } catch (error) {
      return { check: { name, result: 'fail', detail: describeError(error) } };
    }
  }

  // A real stale link cannot be produced on demand. A nextLink with a corrupted position shows
  // how Graph treats a link it cannot use.
  private async probeTamperedNextLink(
    client: GraphClient,
    nextLink: string,
    firstPage: MessagePage,
  ): Promise<{ check: Check; fixture?: Fixture }> {
    const name = 'graphTamperedNextLink';
    const url = new URL(nextLink);
    const positionParam = ['$skiptoken', '$skip'].find((param) => url.searchParams.has(param));
    if (!positionParam) {
      return {
        check: {
          name,
          result: 'inconclusive',
          detail: 'The nextLink has neither $skiptoken nor $skip to corrupt.',
        },
      };
    }
    url.searchParams.set(positionParam, 'corrupted');
    const relative = toRelativeGraphUrl(url.toString());
    if (!relative) {
      return { check: { name, result: 'inconclusive', detail: 'The nextLink is not under v1.0.' } };
    }
    try {
      const [fixture] = await this.batchGet(client, [relative]);
      assert.ok(fixture, 'Microsoft Graph $batch dropped a sub-response');
      const page = parsePage(fixture);
      const restarted = page?.value[0] !== undefined && page.value[0].id === firstPage.value[0]?.id;
      if (restarted) {
        return {
          check: {
            name,
            result: 'fail',
            detail: `Corrupting ${positionParam} returned ${fixture.status} with the first page again. Graph silently restarts a link it cannot use instead of failing, so a followed cursor repeats results and is never reported as expired.`,
          },
          fixture,
        };
      }
      const mappedTo =
        fixture.status === 429 || fixture.status >= 500
          ? 'failed (retryable)'
          : fixture.status >= 400
            ? 'expired'
            : 'a delivered page';
      return {
        check: {
          name,
          result: 'inconclusive',
          detail: `Corrupting ${positionParam} returned ${fixture.status} (${graphErrorCode(fixture.body) ?? 'no error code'}). On a followed cursor this maps to ${mappedTo}.`,
        },
        fixture,
      };
    } catch (error) {
      return { check: { name, result: 'fail', detail: describeError(error) } };
    }
  }

  // The same `i` for two separate searches means an offset into a stable view, which is unlikely to
  // expire. A different `i` per search points at a server-side search session.
  private async probeSkiptokenShape(
    client: GraphClient,
    messagesUrl: string,
    nextLink: string,
    secondPageNextLink: string | undefined,
  ): Promise<Check> {
    const name = 'graphSkiptokenShape';
    try {
      const [repeatFixture] = await this.batchGet(client, [messagesUrl]);
      assert.ok(repeatFixture, 'Microsoft Graph $batch dropped a sub-response');
      const repeatNextLink = parsePage(repeatFixture)?.['@odata.nextLink'];
      const first = decodeSkiptoken(nextLink);
      const second = secondPageNextLink ? decodeSkiptoken(secondPageNextLink) : undefined;
      const repeat = repeatNextLink ? decodeSkiptoken(repeatNextLink) : undefined;
      if (!first) {
        return {
          name,
          result: 'inconclusive',
          detail: 'The $skiptoken does not decode to i/s parameters.',
        };
      }
      if (!repeat) {
        return {
          name,
          result: 'inconclusive',
          detail: `Offsets: page 1 nextLink s=${first.s}, page 2 nextLink s=${second?.s ?? 'n/a'}. The repeated search returned no decodable nextLink.`,
        };
      }
      const sameView = repeat.i === first.i;
      return {
        name,
        result: 'inconclusive',
        detail: `Offsets: page 1 nextLink s=${first.s}, page 2 nextLink s=${second?.s ?? 'n/a'}. The same search run twice returned ${sameView ? 'the same' : 'a different'} i (${first.i} vs ${repeat.i}): ${sameView ? 'a stable view, so links are unlikely to expire' : 'a per-search session, so links can expire'}.`,
      };
    } catch (error) {
      return { name, result: 'fail', detail: describeError(error) };
    }
  }

  // Walks own and full-access delegated mailboxes until one has enough matches to reach the
  // ceiling.
  private async probeCeiling(
    client: GraphClient,
    userProfile: NonNullishProps<UserProfile, 'email'>,
    searchQuery: string,
  ): Promise<{ check: Check; walks: Record<string, CeilingWalkPage[]> }> {
    const mailboxes = await this.listMailboxesAndDirectoriesQuery.run(userProfile.id);
    const searchable = mailboxes.filter(({ hasFullAccess }) => hasFullAccess);
    const walks: Record<string, CeilingWalkPage[]> = {};
    let lastCheck: Check = {
      name: 'graphSearchCeiling',
      result: 'inconclusive',
      detail: 'No mailbox with full access to walk.',
    };
    for (const { email } of searchable) {
      const { check, pages } = await this.walkToCeiling(client, email, searchQuery);
      walks[email] = pages;
      lastCheck = { ...check, detail: `${email}: ${check.detail}` };
      if (check.result !== 'inconclusive') {
        break;
      }
    }
    return { check: lastCheck, walks };
  }

  private async walkToCeiling(
    client: GraphClient,
    mailbox: string,
    searchQuery: string,
  ): Promise<{ check: Check; pages: CeilingWalkPage[] }> {
    const name = 'graphSearchCeiling';
    const pages: CeilingWalkPage[] = [];
    let url: string | undefined =
      `/users/${mailbox}/messages?${searchQuery}&$top=${CEILING_PAGE_SIZE}`;
    try {
      while (url && pages.length < CEILING_MAX_PAGES) {
        const [fixture]: Fixture[] = await this.batchGet(client, [url]);
        assert.ok(fixture, 'Microsoft Graph $batch dropped a sub-response');
        const page = parsePage(fixture);
        const pageNextLink = page?.['@odata.nextLink'];
        pages.push({
          status: fixture.status,
          count: page?.value.length ?? 0,
          hasNextLink: pageNextLink !== undefined,
        });
        url = pageNextLink ? toRelativeGraphUrl(pageNextLink) : undefined;
      }
    } catch (error) {
      return { check: { name, result: 'fail', detail: describeError(error) }, pages };
    }

    const total = pages.reduce((sum, { count }) => sum + count, 0);
    const lastPage = pages.at(-1);
    const emptyPagesWithNextLink = pages.filter(
      ({ count, hasNextLink }) => count === 0 && hasNextLink,
    ).length;
    const summary = `${total} results over ${pages.length} pages of $top=${CEILING_PAGE_SIZE}; ${emptyPagesWithNextLink} empty pages still had a nextLink; last page status ${lastPage?.status}, nextLink: ${lastPage?.hasNextLink}.`;

    if (lastPage && lastPage.status !== 200) {
      return { check: { name, result: 'fail', detail: summary }, pages };
    }
    if (total > GRAPH_SEARCH_CEILING) {
      return {
        check: {
          name,
          result: 'fail',
          detail: `${summary} Graph returned more than ${GRAPH_SEARCH_CEILING} results, so maxResultsPerChain stops chains too early.`,
        },
        pages,
      };
    }
    if (total < GRAPH_SEARCH_CEILING && !lastPage?.hasNextLink) {
      return {
        check: {
          name,
          result: 'inconclusive',
          detail: `${summary} The mailbox has fewer than ${GRAPH_SEARCH_CEILING} matches, so the ceiling was not reached.`,
        },
        pages,
      };
    }
    if (lastPage?.hasNextLink && total < GRAPH_SEARCH_CEILING) {
      return {
        check: {
          name,
          result: 'inconclusive',
          detail: `${summary} Stopped after ${CEILING_MAX_PAGES} pages before reaching the ceiling.`,
        },
        pages,
      };
    }
    return { check: { name, result: 'pass', detail: summary }, pages };
  }

  private async storeStaleLinkCursor(
    userProfile: NonNullishProps<UserProfile, 'email'>,
    relativeNextLink: string,
    firstPage: MessagePage,
  ): Promise<string | undefined> {
    const head = firstPage.value[0];
    const [cursorId] = await this.searchCursorRepository.create(userProfile.id, [
      {
        backend: SearchBackend.MsGraph,
        kqlQuery: PROBE_KQL,
        mailbox: userProfile.email,
        isDelegated: false,
        url: relativeNextLink,
        delivered: firstPage.value.length,
        chainHead: head?.sentDateTime
          ? { id: head.id, sentDateTime: head.sentDateTime }
          : undefined,
      },
    ]);
    return cursorId;
  }

  private async probeUniquePaging(
    userProfile: NonNullishProps<UserProfile, 'email'>,
  ): Promise<Check[]> {
    const name = 'uniquePageIndex';
    try {
      const rootExternalId = getRootScopeExternalId();
      const userRootExternalId = getRootScopeExternalIdForUser(userProfile.providerUserId);
      const scopes = await this.uniqueApi.scopes.getByExternalIds([
        rootExternalId,
        userRootExternalId,
      ]);
      const rootScopeId = scopes.find(({ externalId }) => externalId === rootExternalId)?.id;
      const userRootScopeId = scopes.find(
        ({ externalId }) => externalId === userRootExternalId,
      )?.id;
      if (!rootScopeId || !userRootScopeId) {
        return [{ name, result: 'inconclusive', detail: 'The user has no Unique root scope.' }];
      }
      const metaDataFilter: MetadataFilter = {
        and: [
          {
            operator: UniqueQLOperator.CONTAINS,
            value: `uniquepathid://${rootScopeId}/${userRootScopeId}`,
            path: ['folderIdPath'],
          },
        ],
      };
      const search = async (limit: number, page?: number) => {
        const items = await this.uniqueApi.content.search({
          prompt: UNIQUE_PROBE_PROMPT,
          metaDataFilter,
          limit,
          ...(page === undefined ? {} : { page }),
          scoreThreshold: 0,
        });
        return items.map(({ id, chunkId }) => `${id}#${chunkId}`);
      };
      const calls = {
        withoutPage: () => search(UNIQUE_PAGE_SIZE),
        page0: () => search(UNIQUE_PAGE_SIZE, 0),
        page0Again: () => search(UNIQUE_PAGE_SIZE, 0),
        page1: () => search(UNIQUE_PAGE_SIZE, 1),
        page1Again: () => search(UNIQUE_PAGE_SIZE, 1),
        page2: () => search(UNIQUE_PAGE_SIZE, 2),
        page3: () => search(UNIQUE_PAGE_SIZE, 3),
        doubleLimitPage0: () => search(UNIQUE_PAGE_SIZE * 2, 0),
        doubleLimitPage1: () => search(UNIQUE_PAGE_SIZE * 2, 1),
      };
      const settled = await Promise.allSettled(Object.values(calls).map((call) => call()));
      const outcomes = new Map(
        Object.keys(calls).map((key, i) => {
          const outcome = settled[i];
          assert.ok(outcome, 'Promise.allSettled returned fewer results than calls');
          return [key as keyof typeof calls, outcome] as const;
        }),
      );
      const chunks = (key: keyof typeof calls) => {
        const outcome = outcomes.get(key);
        return outcome?.status === 'fulfilled' ? outcome.value : undefined;
      };
      const callsCheck: Check = {
        name: 'uniqueSearchCalls',
        result: Array.from(outcomes.values()).every(({ status }) => status === 'fulfilled')
          ? 'pass'
          : 'fail',
        detail: Array.from(outcomes, ([key, outcome]) =>
          outcome.status === 'fulfilled'
            ? `${key}: ${outcome.value.length} chunks`
            : `${key}: ${describeError(outcome.reason)}`,
        ).join(' | '),
      };

      const withoutPage = chunks('withoutPage');
      const page0 = chunks('page0');
      const page1 = chunks('page1');
      const firstPageIndex = page0 ? 0 : page1 ? 1 : undefined;
      if (!withoutPage || firstPageIndex === undefined) {
        return [
          callsCheck,
          { name, result: 'fail', detail: 'Not enough calls succeeded to compare pages.' },
        ];
      }
      const [first, firstAgain, second, third, doubleFirst] =
        firstPageIndex === 0
          ? [page0, chunks('page0Again'), page1, chunks('page2'), chunks('doubleLimitPage0')]
          : [
              page1,
              chunks('page1Again'),
              chunks('page2'),
              chunks('page3'),
              chunks('doubleLimitPage1'),
            ];
      if (!first || !firstAgain || !second || !third || !doubleFirst) {
        return [
          callsCheck,
          { name, result: 'fail', detail: 'Some page calls failed, see uniqueSearchCalls.' },
        ];
      }

      const overlap = (a: string[], b: string[]) => a.filter((key) => b.includes(key)).length;
      const isStable = first.join() === firstAgain.join();
      const firstEqualsDefault = first.join() === withoutPage.join();
      const firstEqualsSecond = first.length > 0 && first.join() === second.join();
      const matchesDoublePage = doubleFirst.join() === [...first, ...second].join();
      const detail = `Assuming the first page is ${firstPageIndex}${page0 ? '' : ' (page 0 was rejected)'}. Page sizes: ${first.length}/${second.length}/${third.length}. First page equals the call without \`page\`: ${firstEqualsDefault}. Overlap first∩second: ${overlap(first, second)}, second∩third: ${overlap(second, third)}. limit=${UNIQUE_PAGE_SIZE * 2} on the first page equals the first two pages: ${matchesDoublePage}.`;

      const stabilityCheck: Check = {
        name: 'uniqueStableOrdering',
        result: isStable ? 'pass' : 'fail',
        detail: `The same page requested twice returned the same chunks in the same order: ${isStable}.`,
      };
      if (first.length < UNIQUE_PAGE_SIZE) {
        return [
          callsCheck,
          stabilityCheck,
          { name, result: 'inconclusive', detail: `${detail} Not enough chunks to page.` },
        ];
      }
      if (firstEqualsSecond) {
        return [
          callsCheck,
          stabilityCheck,
          {
            name,
            result: 'fail',
            detail: `${detail} Pages ${firstPageIndex} and ${firstPageIndex + 1} are the same, so \`page\` starts at ${firstPageIndex + 1}.`,
          },
        ];
      }
      const pagesLineUp =
        firstEqualsDefault &&
        overlap(first, second) === 0 &&
        overlap(second, third) === 0 &&
        matchesDoublePage;
      return [
        callsCheck,
        stabilityCheck,
        {
          name,
          result:
            pagesLineUp && firstPageIndex === 0 ? 'pass' : pagesLineUp ? 'fail' : 'inconclusive',
          detail: pagesLineUp
            ? `${detail} \`page\` is ${firstPageIndex}-based with page size = limit.${firstPageIndex === 0 ? '' : ' Production sends page 0 on the first page and must change.'}`
            : detail,
        },
      ];
    } catch (error) {
      return [{ name, result: 'fail', detail: describeError(error) }];
    }
  }
}
