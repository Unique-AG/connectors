export const stripChunkTags = (text: string): string => {
  // To minimize errors in removing chunk tags we always remove the
  // exact tags from the begining of the document always.
  return text
    .trim()
    .replace(/^<\|document\|>[\s\S]*?<\|\/document\|>\n?/g, '')
    .trim()
    .replace(/^<\|title\|>[\s\S]*?<\|\/title\|>\n?/g, '')
    .trim()
    .replace(/^<\|info\|>[\s\S]*?<\|\/info\|>\n?/g, '');
};
