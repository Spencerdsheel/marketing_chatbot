/**
 * Allow-list markdown-to-React renderer (S14.2 decision 3, scope item 4).
 *
 * The bot's `reply` is untrusted text from an LLM, rendered inside a page
 * the widget does not control. This module parses a small, explicit
 * markdown subset into REACT ELEMENTS — never an HTML string, never
 * `dangerouslySetInnerHTML` — so any `<`/`>`/`&`/`"` in the source text is
 * rendered as a literal character via React's default text-node escaping,
 * never parsed as HTML. Anything outside the allow-list renders as plain
 * escaped text.
 *
 * Supported subset: paragraphs (blank-line separated) / single line breaks,
 * **bold**, *italic*, inline `code`, and autolinked bare http(s) URLs
 * (rendered with rel="noopener noreferrer" target="_blank" so a bot-emitted
 * link can never reach window.opener on the host page).
 */
import { Fragment, type ReactNode } from "react";

/** Parse a single line's inline markdown (bold/italic/code/links) into React nodes. */
function parseInline(text: string, keyPrefix: string): ReactNode[] {
  // Tokenize on the inline patterns in priority order: code > bold > italic > url.
  // A single combined regex keeps ordering simple and avoids double-processing
  // matched spans.
  const pattern = /(`([^`]+)`)|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(https?:\/\/[^\s<>"')\]]+)/g;

  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let idx = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const key = `${keyPrefix}-${idx++}`;

    if (match[2] !== undefined) {
      // inline `code`
      nodes.push(<code key={key}>{match[2]}</code>);
    } else if (match[4] !== undefined) {
      // **bold**
      nodes.push(<strong key={key}>{match[4]}</strong>);
    } else if (match[6] !== undefined) {
      // *italic*
      nodes.push(<em key={key}>{match[6]}</em>);
    } else if (match[7] !== undefined) {
      // bare URL
      nodes.push(
        <a key={key} href={match[7]} target="_blank" rel="noopener noreferrer">
          {match[7]}
        </a>,
      );
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

/**
 * Render `text` as a small, safe markdown subset. Splits on blank lines into
 * paragraphs; single newlines within a paragraph become `<br />`. Every
 * text run reaches the DOM only as a React text child (never innerHTML), so
 * raw HTML/script tags in `text` render as inert, visible literal text.
 */
export function Markdown({ text }: { text: string }): ReactNode {
  const paragraphs = text.split(/\n{2,}/);

  return (
    <>
      {paragraphs.map((paragraph, pIdx) => {
        const lines = paragraph.split("\n");
        return (
          <p key={`p-${pIdx}`} className="cw-md-paragraph">
            {lines.map((line, lIdx) => (
              <Fragment key={`l-${lIdx}`}>
                {lIdx > 0 && <br />}
                {parseInline(line, `p${pIdx}-l${lIdx}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}
