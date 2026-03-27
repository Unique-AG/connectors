import { Schema } from "effect"

export interface ODataParams<T> {
  readonly $select?: ReadonlyArray<keyof T & string>
  readonly $filter?: string
  readonly $expand?: ReadonlyArray<keyof T & string>
  readonly $orderby?: ReadonlyArray<`${keyof T & string} ${"asc" | "desc"}`>
  readonly $top?: number
  readonly $skip?: number
  readonly $count?: boolean
  readonly $search?: string
}

export const ODataPage = <A, I, R>(itemSchema: Schema.Schema<A, I, R>) =>
  Schema.Struct({
    value: Schema.Array(itemSchema),
    "@odata.nextLink": Schema.optional(Schema.String),
    "@odata.count": Schema.optional(Schema.Number),
    "@odata.context": Schema.optional(Schema.String),
  })

export type ODataPageType<A> = {
  readonly value: ReadonlyArray<A>
  readonly "@odata.nextLink"?: string
  readonly "@odata.count"?: number
  readonly "@odata.context"?: string
}

export const buildQueryString = <T>(params: ODataParams<T>): string => {
  const parts: string[] = []

  if (params.$select && params.$select.length > 0) {
    parts.push(`$select=${params.$select.join(",")}`)
  }
  if (params.$filter) {
    parts.push(`$filter=${encodeURIComponent(params.$filter)}`)
  }
  if (params.$expand && params.$expand.length > 0) {
    parts.push(`$expand=${params.$expand.join(",")}`)
  }
  if (params.$orderby && params.$orderby.length > 0) {
    parts.push(`$orderby=${params.$orderby.join(",")}`)
  }
  if (params.$top !== undefined) {
    parts.push(`$top=${params.$top}`)
  }
  if (params.$skip !== undefined) {
    parts.push(`$skip=${params.$skip}`)
  }
  if (params.$count !== undefined) {
    parts.push(`$count=${params.$count}`)
  }
  if (params.$search) {
    parts.push(`$search=${encodeURIComponent(params.$search)}`)
  }

  return parts.length > 0 ? `?${parts.join("&")}` : ""
}
