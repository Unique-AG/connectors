from kiota_abstractions.headers_collection import HeadersCollection


def immutable_id_headers() -> HeadersCollection:
    headers = HeadersCollection()
    headers.add("Prefer", 'IdType="ImmutableId"')
    return headers
