/**
 * Tiny markdown renderer for design annotations.
 *
 * react-markdown is not in the dependency tree, so we hand-roll a
 * deliberately small subset that:
 *
 *   - escapes all HTML
 *   - renders **bold**, *italic*, `code`
 *   - renders fenced code blocks (```lang ... ```)
 *   - renders [link text](url)
 *   - renders @mentions against an org-roster array
 *   - turns blank-line-separated paragraphs into <p>
 *   - renders unordered lists (`- ` / `* `) as <ul><li>
 *
 * This is good enough for short collaboration notes and avoids shipping a
 * 30 kB markdown lib for a handful of comment threads. If we ever need
 * tables, footnotes, or syntax highlighting, swap in `react-markdown` +
 * `remark-gfm` and delete this file.
 */

import type { OrgMember } from "./CommentEditor";

const ESC: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESC[c] ?? c);
}

function isSafeUrl(url: string): boolean {
  // Allow http(s), mailto, and relative paths starting with `/`.
  return /^(https?:\/\/|mailto:|\/)/i.test(url.trim());
}

function renderInline(line: string, members: OrgMember[]): string {
  let html = escapeHtml(line);

  // Inline code first so we don't accidentally bold/italicize inside code.
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // [text](url)
  html = html.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_m, text: string, url: string) => {
      if (!isSafeUrl(url)) return escapeHtml(`[${text}](${url})`);
      return `<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    },
  );

  // **bold** and *italic*. Done after links so we don't eat link syntax.
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*]+)\*/g, "$1<em>$2</em>");

  // @mentions: match handles formed by stripping whitespace from member name.
  if (members.length > 0) {
    const handles = new Map<string, OrgMember>();
    for (const m of members) {
      const name = (m.name ?? m.email).replace(/\s+/g, "");
      if (name) handles.set(name.toLowerCase(), m);
    }
    html = html.replace(/(^|[^A-Za-z0-9_])@([A-Za-z0-9._-]+)/g, (m, pre: string, h: string) => {
      const member = handles.get(h.toLowerCase());
      if (!member) return m;
      return `${pre}<span class="mention" data-uid="${member.userId}">@${escapeHtml(h)}</span>`;
    });
  }

  return html;
}

export function renderMarkdown(src: string, members: OrgMember[] = []): string {
  if (!src.trim()) {
    return '<p class="text-graphite-soft italic">Nothing to preview.</p>';
  }

  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const blocks: string[] = [];
  let buf: string[] = [];
  let listBuf: string[] = [];
  let inFence = false;
  let fenceLang = "";
  let fenceBuf: string[] = [];

  function flushPara() {
    if (buf.length === 0) return;
    const inner = buf
      .map((l) => renderInline(l, members))
      .join("<br/>");
    blocks.push(`<p>${inner}</p>`);
    buf = [];
  }
  function flushList() {
    if (listBuf.length === 0) return;
    blocks.push(
      `<ul>${listBuf
        .map((l) => `<li>${renderInline(l, members)}</li>`)
        .join("")}</ul>`,
    );
    listBuf = [];
  }

  for (const raw of lines) {
    const line = raw;
    if (inFence) {
      if (/^```\s*$/.test(line)) {
        const code = escapeHtml(fenceBuf.join("\n"));
        const cls = fenceLang ? ` class="language-${escapeHtml(fenceLang)}"` : "";
        flushPara();
        flushList();
        blocks.push(`<pre><code${cls}>${code}</code></pre>`);
        fenceBuf = [];
        fenceLang = "";
        inFence = false;
      } else {
        fenceBuf.push(line);
      }
      continue;
    }
    const fenceOpen = /^```\s*([A-Za-z0-9_-]*)\s*$/.exec(line);
    if (fenceOpen) {
      flushPara();
      flushList();
      inFence = true;
      fenceLang = fenceOpen[1] ?? "";
      continue;
    }
    if (/^\s*$/.test(line)) {
      flushPara();
      flushList();
      continue;
    }
    const li = /^\s*[-*]\s+(.*)$/.exec(line);
    if (li) {
      flushPara();
      listBuf.push(li[1] ?? "");
      continue;
    }
    flushList();
    buf.push(line);
  }
  if (inFence) {
    // Unterminated fence: flush as paragraph so we don't lose content.
    buf.push(...fenceBuf);
    fenceBuf = [];
    inFence = false;
  }
  flushPara();
  flushList();

  return blocks.join("");
}
