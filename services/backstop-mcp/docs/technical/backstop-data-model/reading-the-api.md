# Reading the API

> **Before you read.** [Basics](basics.md): collections, views and id spaces.

This chapter covers everything you need to make correct `GET` requests: addresses, credentials,
the response format, related data, paging, filters and sorting. Writing is covered separately in
[Writing data](writing-data.md), and every error message is listed in [Errors](errors.md).

## Addresses

```
https://<host>/backstop/api/<collection>[/<id>[/<relationship>]]
https://<host>/<collection>[/<id>[/<relationship>]]
```

- Both forms answer. Links inside responses use the first. This server uses the second:
  `BACKSTOP_BASE_URL` is the bare origin and every request path is `/<collection>…`, while
  `paginate()` follows the `/backstop/api/…` links Backstop returns. These docs write paths
  without the prefix.
- `<host>` is either the tenant's own host (`<firm>.backstopsolutions.com`) or the shared
  `api.backstopsolutions.com`. Both work.
- There is no version in the URL and no version header. Versions are per resource type and set
  by the tenant's administrator (see [Basics](basics.md#where-knowledge-comes-from)). The
  swagger for those versions does not document the full API: probing a resource type on a
  different version sometimes still returns a response.
- Links inside responses echo whichever server answered. Older responses carry an internal host
  of the form `fb-<server>.backstopsolutions.com`. **Never build a URL from a `links` value; build it
  from the id.** The one exception is `BackstopClient.paginate()`, which follows `links.next`
  verbatim but pins scheme and host to `BACKSTOP_BASE_URL`. A `next` link on an `fb-…` host
  raises `BackstopUntrustedUrlError` and fails the walk. Use `fetch_page` with explicit offsets
  where that matters.

## Credentials and headers

- HTTP Basic authentication over HTTPS: `Authorization: Basic base64(<username>:<secret>)`.
- `<secret>` is the user's password or, more usually, a personal **API token**. With a token, add
  the header `token: true`. Users who sign in through single sign-on have no password and must use
  a token (*documented*, articles 1018 and 236).
- Tokens are created in the web app under *Update Your Profile › API Security*. Administrators set
  their expiry and can revoke them.
- Every call runs with the permissions of the user who owns the token.
- Send `Accept: application/vnd.api+json` (or no `Accept` at all). **`Accept: application/json`
  returns an HTML "404 Not Found" page**, even for a record that exists.

Two authentication answers look alike but mean different things:

| Response | Meaning |
|---|---|
| `401`, HTML body "Invalid username/password provided." | Wrong credentials. Repeated failures add a warning that the next one will lock the account. Stop retrying. |
| `401`, plain text "You are not authorized to access this API." | Credentials are fine, but the path is not part of the API (`/me`, `/parties`, a misspelt collection). |

A `403` means "authenticated but not allowed". It comes in several forms (whole resource type,
single record, read-only view), all listed in [Errors](errors.md#403).

## The response format

Responses look like [JSON:API](https://jsonapi.org/) but do not follow it fully.

A collection:

```json
{
  "data": [
    {
      "id": "101",
      "type": "organizations",
      "attributes": { "name": "…", "createdTimestamp": "2020-04-27T10:15:02.000-0400" },
      "relationships": {
        "representative": { "links": { "self": "…", "related": "…/organizations/101/representative" } }
      },
      "links": { "self": "…/organizations/101" }
    }
  ],
  "included": [],
  "meta": { "totalResourceCount": 2500 },
  "links": { "first": "…", "next": "…", "last": "…" }
}
```

A single record has `data` as an object, an `included` array, and no `meta` or top-level `links`.

What to know:

- `type` is the plural, hyphenated collection name (`meeting-or-calls`). Relationship names are
  camelCase (`meetingOrCalls`, `contactLocations`). A sub-route uses the **relationship name**:
  `/organizations/{id}/meetingOrCalls`. The hyphenated form returns an HTML 404.
- **Attributes whose value is null are left out.** A missing key means "no value", not "unknown
  field". For example, an open account has no `closedDate` key at all.
- A relationship carries only `links` unless you `include` it, in which case it also gets `data`
  pointers.
- `meta.totalResourceCount` is the only `meta` member.
- Timestamps are ISO 8601 with milliseconds and an offset without a colon, in the tenant's time
  zone: `2026-08-24T04:22:23.785-0400`. Fields that really hold a date come back as local midnight
  (`2026-09-14T00:00:00.000-0400`).
- A few resources return `links` as the literal *string* `"{ }"` instead of an object (time-series
  rows, employees, system features, `reports` rows and `bulk-*` responses). Code that expects an
  object must tolerate that.
- Custom field values are an attribute, `regularCustomFieldValues`: a list of
  `{definitionId, name, value}`. See [Custom fields](custom-fields-and-reference-data.md).

Errors use `{"errors": [...]}` in two styles, and a client has to accept both:

```json
{"errors": [{"code": "InvalidParameterException", "title": "Invalid filter field bogus"}]}
{"errors": [{"status": "400", "title": "Request parameters error", "detail": "page[size]=[10]"}]}
```

Some errors are not JSON at all: most 401s, some 403s, the HTML 404 page, and 429.

## Fetching records by id

- `GET /{collection}/{id}`. An id that is not a number, or is larger than 2,147,483,647, gives
  `400 Resource <type> with id <x> is invalid`. A well-formed id that does not exist gives `404`.
- **Several ids in one call:** separate them with commas in the path,
  `GET /organizations/101,102,103`. The answer is a collection with `meta.totalResourceCount` equal
  to the number found (*documented*, article 1289).
- A comma list inside a filter does **not** work: `filter[id][eq]=1,2,3` returns a 500 on several
  collections, and `filter[id][in]` is not an operator.

## Related data: follow the link, or include it

There are two ways to get the records a relationship points to.

**Follow the link.** `GET /{collection}/{id}/{relationship}`, which is the
`relationships.<name>.links.related` URL. It is paged, filtered and sorted on its own. Use it for
big lists such as a contact's activities.

```
GET /organizations/101/employees?page[limit]=50
```

**Include it.** `?include=a,b` puts the related records into the top-level `included` array, and
`relationships.<name>.data` then holds `{type, id}` pointers into it.

```
GET /opportunities?include=investor,investor.representative,stage&page[limit]=50
```

- Nested includes work with dots (`investor.representative`).
- Each collection accepts its own list of include names. Others give
  `400 The system does not support includes for <names>`.
- When you page through a collection with `include=`, the same included records repeat on every
  page. De-duplicate them by `(type, id)`.
- The relationship's own `links.self` (`/{collection}/{id}/relationships/{name}`) returns just the
  ids, for example `{"data": [{"id": "…", "type": "contact-categories"}]}`.

Some limits:

- You cannot go deeper by id: `/organizations/{id}/employees/{personId}` returns
  `500 RelationshipsPath and FieldPath cannot contain ids`. Fetch the child from its own
  collection.
- Some links are attributes, not relationships (`regarding` on a meeting, `sourceEntity` on an
  entity relationship). They cannot be included or followed as sub-routes.

## Choosing fields

`fields[<type>]=a,b` returns only those attributes for that type, including types in `included`.
A bare `fields=a,b` applies to the main type.

```
GET /organizations?include=representative&fields[organizations]=name,representative&fields[system-users]=userName
```

- When you use `fields`, the `relationships` block disappears unless you list the relationship
  name in `fields` or `include`.
- Custom field values are dropped too unless you list `regularCustomFieldValues`.
- An unknown field gives `400 The system does not support fields for <names>`.
- Some hidden attributes stay hidden even when you ask for them by name.

Sparse fields make a real difference on records that carry many custom fields.

## Paging

Always send `page[limit]` when reading a collection. Without it the API returns the whole collection, up to a documented cap of 10,000 rows (*documented*, article 1023), and that payload is large enough to crash a tool.

```
GET /organizations?page[offset]=100&page[limit]=50
```

| Rule | Detail |
|---|---|
| Offset paging only | `page[offset]` and `page[limit]`. `page[size]` and `page[number]` are rejected with a 400. |
| **Offset must be a multiple of limit** | `offset 2 is not a multiple of limit 3` (400). Enforced everywhere, including sub-routes. |
| `page[limit]=0` | 400 `Page limit should be larger than zero`. |
| Large pages | 500 rows per page work on the main collections. The real maximum is unknown. |
| No paging parameters | Returns everything, up to the 10,000-row cap above. |
| Total | `meta.totalResourceCount` on every paged list. |
| Links | `first`, `last`, and `prev` / `next` where they exist. `links` is missing when everything fits on one page. |
| Past the end | 200 with empty `data`; the total is still correct. |

Watch out for:

- **Records can move between pages.** Records that tie on the sort key come back in a different
  order from one request to the next. When you walk a whole collection, sort by `id`.
- **Some endpoints ignore paging.** `/custom-field-definitions` always returns the whole catalogue
  (several megabytes) while still showing a `next` link.
- **Some totals are not totals.** `/quick-search` reports `4 × (offset + limit)`, and
  date-filtered activity feeds report "rows so far". Stop when a page comes back shorter than
  `page[limit]`.
- Some collections refuse to list without a filter, for example
  `400 Find all contact-locations is not allowed.` or
  `400 You can not query all notes without filter criteria.`

## Filtering

```
GET /organizations?filter[name][like]=acme&filter[createdTimestamp][ge]=2026-01-01
```

Several filters are combined with AND. There is no OR: run several requests and merge by id.

### Operators

| Operator | Behaviour |
|---|---|
| `eq` | Exact match. **Case-sensitive** on text ("London" matches, "LONDON" does not). |
| `neq` | Not equal. Appears to include records where the field is empty. |
| `gt`, `ge`, `lt`, `le` | Greater/less than. For dates, numbers and ids. |
| `like` | **Case-insensitive substring** match. Works only on some text fields (see below). There is no wildcard: `%` and `*` are matched literally. Not listed in the swagger, but it works. |

The operator name itself is not case-sensitive (`[LIKE]` works). Anything else (`in`, `contains`,
`startsWith`) is not an operator: Backstop glues it onto the field name and answers
`Invalid filter field city.in`.

`like` works on `name` for organizations, products, accounts, activity tags, contact categories
and relationship types, and on `lastName` for people. On people, `name` takes `eq` only. On system
users, `name` and `lastName` with `like` were seen to work (*observed*), but
`system_users_service.py` says `/system-users` takes no search filter, and this server walks the
whole roster instead.

### Which fields you can filter on

Each collection has a fixed whitelist. The swagger's `filterField` list for that route is a good
guide. A field outside it gives `400 Invalid filter field <x>`; an allowed field with an allowed
operator the field does not support gives `400 Unsupported filter operator: LIKE`.

Some useful fields work although the swagger does not list them:

| Filter | Where |
|---|---|
| `filter[owner.id][eq]=<contactId>` | `/accounts`: the accounts one investor owns (*observed*; this server does not rely on it and filters owners in code) |
| `filter[product.id][eq]`, `filter[product.shortName][eq]` | `/accounts`: the accounts in one product |
| `filter[contactLocations.city][eq]` | `/organizations`, `/people` (exact, case-sensitive) |
| `filter[representative.name][eq]=<login>` | `/opportunities`: the representative's login, exact and case-sensitive |

Things you **cannot** filter on server-side, so you filter in your own code:

- **Custom field values**, on any record. `filter[regularCustomFieldValues.definitionIds][eq]=<id>,<id>`
  is accepted, but it only trims the custom fields returned on each record. It does not remove
  records.
- Many obvious attributes: a person's `firstName`, `jobTitle` or `companyName`; an organization's
  `country`; a product's `productType`; an opportunity's `isOpen` or stage.

### Dates

- Use `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` (no offset needed). They are read in the tenant's time
  zone.
- `01/01/2026` gives `400 Can not convert 01/01/2026 to java.util.Date type.`
- For a window, send two filters on the same field: `filter[modifiedTimestamp][ge]=…&filter[modifiedTimestamp][lt]=…`.

### Bean names in filters

A few read filters want Backstop's internal class name instead of the collection name:
`/custom-field-definitions?filter[entityType][eq]=OpportunityBean`, or
`/tasks?filter[entityType][eq]=OrganizationBean`. A collection name there gives
`400 No enum constant …EntityType.opportunities`. Write payloads are the opposite: they reject Bean
names (see [Writing data](writing-data.md)).

The two use different names for the same records:

| `entityType` on | Bean names in this server's code |
|---|---|
| `/tasks` (filter) | `OrganizationBean`, `PersonBean`, `ContactBean` (contacts), `EmployeeBean` (employees) |
| `/custom-field-definitions` (filter and attribute) | `OrganizationBean`, `PersonBean`, `PartyBean` (contacts), `OpportunityBean`, `ProductBean`, `AccountBean` |

## Sorting

- `sort=<field>` ascending, `sort=-<field>` descending.
- **One field only.** `sort=name,id` gives `400 You can only sort by one field.`
- Each collection has a fixed list of sortable fields (the swagger's `sortField`). A field outside
  it gives `400 Invalid filter field <x>`: the message says "filter" even for a sort.
- **The swagger list is not reliable.** `/people?sort=name` is listed but always returns a 500.
  Use `sort=lastName`.
- Without `sort`, main collections come back in ascending `id`, so an unsorted walk starts with
  the oldest records. Sub-routes and some reference lists have no fixed order.

## Parameters Backstop does not recognise

Behaviour depends on the endpoint:

- **Main collections reject them.** `/organizations?bogus=1` gives `400 Invalid filter field bogus`.
- **Single-record `GET`s ignore them.**
- **A few lenient endpoints ignore them silently**, notably `/custom-field-definitions` (unknown
  filters return the full catalogue) and `/quick-search` (the operator is ignored).

So "no error" is not proof that a filter was applied. When it matters, compare the count with and
without the filter.

The code comments in `backstop_client/settings.py` and `backstop_client/client.py`, and the
backstop-api skill, say Backstop ignores unknown parameters everywhere, and that a misspelt paging
parameter makes Backstop pick its own page size. That holds only for the lenient endpoints above.
On a main collection the same mistake is a 400.

## Limits and speed

- Limits per user: 1,000 requests per minute, 50,000 per hour, 500,000 per day, and at most
  **5 requests in flight at once** (*documented*, article 1249).
- Going over the concurrency limit returns a **429 as an HTML page** titled "Too Many Connections".
  It carries no JSON. We have only ever seen it when firing requests in parallel.
- This server's 429 retry (`backstop_client/retry.py`) retries only when the JSON body names a
  concurrency limit, so an HTML 429 is surfaced unretried. The per-user gate in
  `backstop_client/factory.py` (5 slots) is what keeps the server under the limit.
- Small filtered requests answer in 0–2 seconds. Saved reports are slow (next section). A very
  broad request can take minutes; we stop and treat the API as down after 2 minutes (10 minutes
  for `/reports` and `/analytics`).

## Saved reports

Backstop's Report Builder lets users save cross-record reports. The API can run a saved report by
name; it cannot list them (*documented*, article 389).

```
GET /reports?filter[reportName][eq]=<exact name>&filter[asOfDate][eq]=YYYY-MM-DD&page[limit]=500&page[offset]=0
```

- `reportName` must match the name shown in Report Center exactly, otherwise
  `400 Report '<name>' not found.`
- **A page is not a list of rows.** Each page is one `reports` resource. The columns are in
  `attributes.result.header` and the rows in `attributes.result.values`. `page[offset]`,
  `page[limit]` and `meta.totalResourceCount` count rows, not entries of `data`, so
  `BackstopClient.paginate()` does not fit. This server uses `fetch_page` and advances the offset
  by the rows it received.
- Instead of a name you can send a `reportDefinition` with a `restrictionExpression`
  (`${true}` means no restriction). Send long definitions with `POST`: in the query string they hit
  `414 Request-URI Too Large`.
- The swagger marks every parameter as required. Send an empty value for the ones you do not use.
- Reports are slow, up to about 30 seconds per 500 rows, and a report that is not cached can take
  minutes before the first byte. Backstop recommends at most 500 rows per page.
- A report cannot be filtered by the API beyond its own saved restriction. Page through it and
  filter on its columns.

## Where to look next

- Finding a contact by name or email: [Contacts › Finding contacts](contacts.md#finding-contacts).
- Every error message: [Errors](errors.md).
