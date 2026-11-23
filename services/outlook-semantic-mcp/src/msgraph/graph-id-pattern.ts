/**
 * The characters of a Graph message or folder id, which go into a URL path unescaped. Anything
 * else, such as `?`, `#`, `%` or `&`, could change which resource the request reaches.
 */
export const GRAPH_ID_PATTERN = /^[A-Za-z0-9+/_=-]+$/;
