import assert from 'node:assert';
import type { Element } from 'domhandler';
import { DomUtils, parseDocument } from 'htmlparser2';

export type ResourceRef =
  | { kind: 'current-attachment'; filename: string }
  | {
      kind: 'other-page-attachment';
      filename: string;
      spaceKey: string;
      contentTitle: string;
    }
  | { kind: 'external-url' }
  | { kind: 'unknown' };

export interface ParsedImageMacro {
  startIndex: number;
  endIndex: number;
  imgAttrs: Record<string, string>;
  resourceRef: ResourceRef;
}

// Locates every <ac:image> macro in a Confluence format. htmlparser2 only knows generic XML, so stringifying
// the whole tree back can change parts of the page we never touched. Because of this we replace the ac:image tags.
export function parseImageMacros(body: string): ParsedImageMacro[] {
  const doc = parseDocument(body, {
    xmlMode: true,
    withStartIndices: true,
    withEndIndices: true,
  });

  return DomUtils.getElementsByTagName('ac:image', doc).map((node) => {
    assert.ok(
      node.startIndex != null && node.endIndex != null,
      'node positions missing — parseDocument needs withStartIndices/withEndIndices',
    );

    return {
      startIndex: node.startIndex,
      endIndex: node.endIndex + 1,
      imgAttrs: node.attribs,
      resourceRef: resolveResourceRef(node),
    };
  });
}

// Returns the first direct child element with the given tag name. recurse=false keeps the
// search to immediate children so a nested <ri:page> can never satisfy a <ri:attachment> lookup.
function firstChildElementByName(parent: Element, name: string): Element | undefined {
  return DomUtils.findOne((el) => el.name === name, parent.children, false) ?? undefined;
}

function resolveResourceRef(imageNode: Element): ResourceRef {
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
      return { kind: 'other-page-attachment', filename, spaceKey, contentTitle };
    }
    // <ri:page> is present but malformed (missing ri:space-key or ri:content-title).
    // Falling through to 'current-attachment' would risk inlining the wrong image if
    // the current page happens to have an attachment with the same filename.
    return { kind: 'unknown' };
  }
  return { kind: 'current-attachment', filename };
}
