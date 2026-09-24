/**
 * Where the app lives. A deployment can serve it under a sub-path (say /rp/), and then every URL the components
 * build from the root of the app has to carry that prefix. Rather than have every component know about it, the
 * request helpers and the few places that navigate pass their URLs through rootUrl(), which reads the prefix from
 * the URLS map the app's frame publishes. Without a map, or with a root of "/", nothing changes.
 */

export const getAppRoot = (): string => {
  const root = (window as any).URLS?.root || '/';
  return root.endsWith('/') ? root : `${root}/`;
};

/**
 * Resolves a root-absolute app path ("/api/v2/…") against the app root. Absolute URLs, protocol-relative URLs,
 * relative paths and paths already under the root pass through unchanged.
 */
export const rootUrl = (url: string): string => {
  const root = getAppRoot();
  if (
    root === '/' ||
    !url ||
    !url.startsWith('/') ||
    url.startsWith('//') ||
    url.startsWith(root)
  ) {
    return url;
  }
  return root + url.substring(1);
};
