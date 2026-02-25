export const sanitizePath = ({
  path,
  prefixWithSlash,
}: {
  path: string;
  prefixWithSlash: boolean;
}): string => {
  const newPath = path
    .split('/')
    .filter((pathPart) => pathPart.length > 0)
    .join('/');

  if (!prefixWithSlash) {
    return newPath;
  }
  return `/${newPath}`;
};
