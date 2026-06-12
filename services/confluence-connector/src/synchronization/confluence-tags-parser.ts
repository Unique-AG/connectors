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
export function findAllImageMacros(body: string): ParsedImageMacro[] {
  const doc = parseDocument(body, {
    xmlMode: true,
    withStartIndices: true,
    withEndIndices: true,
  });

  return DomUtils.getElementsByTagName('ac:image', doc).flatMap((node) => {
    assert.ok(
      node.startIndex != null && node.endIndex != null,
      'node positions missing — parseDocument needs withStartIndices/withEndIndices',
    );
    const endIndex = node.endIndex + 1;

    // htmlparser2 auto-closes an unclosed <ac:image> by absorbing the following siblings, which
    // inflates the range and would make us splice away real body content. If the source doesn't
    // actually close the tag, skip the macro and leave the body untouched.
    if (!/<\/ac:image\s*>$/.test(body.slice(node.startIndex, endIndex))) {
      return [];
    }

    return [
      {
        startIndex: node.startIndex,
        endIndex,
        imgAttrs: node.attribs,
        resourceRef: resolveResourceRef(node),
      },
    ];
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
