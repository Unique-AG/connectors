import { useEffect, useRef, useState } from 'react';

interface SafeHtmlRendererProps {
  html: string;
  className?: string;
}

export const SafeHtmlRenderer = ({ html, className = '' }: SafeHtmlRendererProps) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [iframeHeight, setIframeHeight] = useState(0);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
    if (!iframeDoc) return;

    const sanitizedHtml = sanitizeEmailHtml(html);

    const fullHtml = `
      <!DOCTYPE html>
      <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {
              margin: 0;
              padding: 16px;
              font-family: system-ui, -apple-system, sans-serif;
              font-size: 14px;
              line-height: 1.5;
              color: #000;
              background: transparent;
              word-wrap: break-word;
              overflow-wrap: break-word;
            }
            
            /* Reset potentially dangerous styles */
            * {
              max-width: 100%;
            }
            
            img {
              height: auto;
              max-width: 100%;
            }
            
            table {
              border-collapse: collapse;
              max-width: 100%;
            }
            
            /* Ensure links are visible */
            a {
              color: #0066cc;
              text-decoration: underline;
            }
            
            /* Prevent position fixed/absolute from escaping */
            * {
              position: static !important;
            }
          </style>
        </head>
        <body>
          ${sanitizedHtml}
        </body>
      </html>
    `;

    iframeDoc.open();
    iframeDoc.write(fullHtml);
    iframeDoc.close();

    const updateHeight = () => {
      const body = iframeDoc.body;
      const html = iframeDoc.documentElement;
      const height = Math.max(
        body?.scrollHeight || 0,
        body?.offsetHeight || 0,
        html?.scrollHeight || 0,
        html?.offsetHeight || 0
      );
      setIframeHeight(height);
    };

    updateHeight();

    const resizeObserver = new ResizeObserver(updateHeight);
    if (iframeDoc.body) {
      resizeObserver.observe(iframeDoc.body);
    }

    return () => {
      resizeObserver.disconnect();
    };
  }, [html]);

  return (
    <iframe
      ref={iframeRef}
      title="Email content"
      sandbox="allow-same-origin"
      style={{
        width: '100%',
        height: iframeHeight ? `${iframeHeight}px` : '400px',
        border: 'none',
        display: 'block',
      }}
      className={className}
    />
  );
};

function sanitizeEmailHtml(html: string): string {
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = html;

  const dangerousElements = tempDiv.querySelectorAll(
    'script, style, iframe, object, embed, link[rel="stylesheet"], base, meta[http-equiv]'
  );
  dangerousElements.forEach((el) => {
    el.remove();
  });

  const allElements = tempDiv.querySelectorAll('*');
  allElements.forEach((el) => {
    const dangerousAttrs = [
      'onload',
      'onerror',
      'onclick',
      'onmouseover',
      'onmouseout',
      'onmouseenter',
      'onmouseleave',
      'onfocus',
      'onblur',
      'onchange',
      'onsubmit',
    ];

    dangerousAttrs.forEach((attr) => {
      if (el.hasAttribute(attr)) {
        el.removeAttribute(attr);
      }
    });

    if (el.hasAttribute('href')) {
      const href = el.getAttribute('href') || '';
      if (href.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute('href');
      }
    }

    if (el.hasAttribute('src')) {
      const src = el.getAttribute('src') || '';
      if (src.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute('src');
      }
    }

    if (el.hasAttribute('style')) {
      const style = el.getAttribute('style') || '';
      if (
        style.toLowerCase().includes('javascript:') ||
        style.toLowerCase().includes('expression(') ||
        style.toLowerCase().includes('behavior:')
      ) {
        el.removeAttribute('style');
      }
    }
  });

  return tempDiv.innerHTML;
}

