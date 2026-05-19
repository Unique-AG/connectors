import { type Element, isTag, type ParentNode } from 'domhandler';
import { parseDocument } from 'htmlparser2';

export type ResourceRef =
  | { kind: 'current-attachment'; filename: string }
  | {
      kind: 'cross-page-attachment';
      filename: string;
      spaceKey: string;
      contentTitle: string;
    }
  | { kind: 'external-url' }
  | { kind: 'unknown' };

export interface ParsedImageBlock {
  startIndex: number;
  endIndex: number;
  imgAttrs: Record<string, string>;
  resource: ResourceRef;
}

// Locates every <ac:image> macro in a Confluence storage-format body and returns its
// byte range, attributes, and resolved resource reference. The byte ranges are intended
// for surgical splicing back into the original string so content outside the macros is
// preserved byte-for-byte.
export function parseImageBlocks(body: string): ParsedImageBlock[] {
  const doc = parseDocument(body, {
    xmlMode: true,
    withStartIndices: true,
    withEndIndices: true,
  });

  const imageNodes: Element[] = [];
  collectElementsByName(doc, 'ac:image', imageNodes);

  const blocks: ParsedImageBlock[] = [];
  for (const node of imageNodes) {
    if (node.startIndex == null || node.endIndex == null) {
      continue;
    }
    // Element.endIndex points at the final '>' of either '</ac:image>' or self-closing
    // '/>', so +1 is exclusive. Reject blocks whose slice does not terminate with a
    // real close so an unclosed macro can never splice into unrelated content.
    const endIndex = node.endIndex + 1;
    const blockText = body.slice(node.startIndex, endIndex);
    if (!blockText.endsWith('</ac:image>') && !blockText.endsWith('/>')) {
      continue;
    }
    blocks.push({
      startIndex: node.startIndex,
      endIndex,
      imgAttrs: node.attribs,
      resource: resolveResourceFromNodes(node),
    });
  }
  return blocks;
}

function collectElementsByName(parent: ParentNode, name: string, out: Element[]): void {
  for (const child of parent.children) {
    if (!isTag(child)) {
      continue;
    }
    if (child.name === name) {
      out.push(child);
      // <ac:image> is never nested inside another <ac:image>; no need to recurse into hits.
      continue;
    }
    collectElementsByName(child, name, out);
  }
}

function firstChildElementByName(parent: Element, name: string): Element | undefined {
  for (const child of parent.children) {
    if (isTag(child) && child.name === name) {
      return child;
    }
  }
  return undefined;
}

function resolveResourceFromNodes(imageNode: Element): ResourceRef {
  const url = firstChildElementByName(imageNode, 'ri:url');
  if (url) {
    return { kind: 'external-url' };
  }
  const attachment = firstChildElementByName(imageNode, 'ri:attachment');
  if (!attachment) {
    return { kind: 'unknown' };
  }
  const filename = attachment.attribs['ri:filename'];
  if (!filename) {
    return { kind: 'unknown' };
  }
  const page = firstChildElementByName(attachment, 'ri:page');
  if (page) {
    const spaceKey = page.attribs['ri:space-key'];
    const contentTitle = page.attribs['ri:content-title'];
    if (spaceKey && contentTitle) {
      return { kind: 'cross-page-attachment', filename, spaceKey, contentTitle };
    }
  }
  return { kind: 'current-attachment', filename };
}
