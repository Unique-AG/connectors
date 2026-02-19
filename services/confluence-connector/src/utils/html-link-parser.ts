const HREF_REGEX = /href=["']([^"']*)["']/g;

export function parseHrefs(html: string): string[] {
  const seen = new Set<string>();
  const hrefs: string[] = [];

  for (const match of html.matchAll(HREF_REGEX)) {
    const href = match[1];
    if (href && !seen.has(href)) {
      seen.add(href);
      hrefs.push(href);
    }
  }

  return hrefs;
}

export function stripQueryAndFragment(url: string): string {
  const queryIndex = url.indexOf('?');
  const fragmentIndex = url.indexOf('#');
  const endIndex = Math.min(
    queryIndex === -1 ? url.length : queryIndex,
    fragmentIndex === -1 ? url.length : fragmentIndex,
  );
  return url.substring(0, endIndex);
}

export function extractFileUrls(
  html: string,
  allowedExtensions: string[],
  baseUrl: string,
): string[] {
  const urls: string[] = [];

  for (const href of parseHrefs(html)) {
    const cleanUrl = stripQueryAndFragment(href);
    const extension = cleanUrl.split('.').pop()?.toLowerCase();
    if (extension && allowedExtensions.includes(extension)) {
      urls.push(new URL(href, baseUrl).toString());
    }
  }

  return urls;
}
