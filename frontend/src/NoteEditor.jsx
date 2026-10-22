import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Bold,
  Check,
  Code,
  Columns2,
  Eye,
  Heading2,
  Italic,
  List,
  ListOrdered,
  LoaderCircle,
  Maximize2,
  Minimize2,
  PenLine,
  Quote,
  Search,
} from "lucide-react";
import { api } from "./api";
import { ErrorBox } from "./ui";

// 본문의 [cN]을 인용 칩으로 바꾸려고 Markdown 링크(#cite-cN)로 미리 바꿔 둔다.
const withCitationLinks = (body) => body.replace(/\[(c\d+)\](?!\()/g, "[$1](#cite-$1)");

// 저장된 노트·미리보기용 Markdown 렌더러. [cN]은 누르면 원본을 여는 칩으로 보인다.
export function NoteMarkdown({ body, citations = [], onCite }) {
  const byId = new Map(citations.map((c) => [c.id || c.citation_id, c]));
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href = "", children }) {
            if (href.startsWith("#cite-")) {
              const id = href.slice(6),
                c = byId.get(id);
              const label = c ? (c.source_type === "note" ? "내 노트" : `${c.page}쪽`) : "";
              return (
                <button
                  type="button"
                  className={`cite-chip ${c?.source_type === "note" ? "note" : "doc"}`}
                  onClick={() => c && onCite?.(c)}
                  disabled={!c || c.missing || !onCite}
                  title={c?.quote || c?.title || ""}
                >
                  {id}
                  {label && <small>{label}</small>}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {withCitationLinks(body)}
      </ReactMarkdown>
    </div>
  );
}

// 선택 영역을 앞뒤 기호로 감싸거나, 줄 앞에 기호를 붙인다.
function applyFormat(textarea, body, kind) {
  const { selectionStart: start, selectionEnd: end } = textarea;
  const selected = body.slice(start, end);
  const wrap = { bold: "**", italic: "_", code: "`" }[kind];
  if (wrap) {
    const inner = selected || { bold: "굵게", italic: "기울임", code: "코드" }[kind];
    const next = body.slice(0, start) + wrap + inner + wrap + body.slice(end);
    return { next, from: start + wrap.length, to: start + wrap.length + inner.length };
  }
  const prefix = { h2: "## ", list: "- ", ordered: "1. ", quote: "> " }[kind];
  const lineStart = body.lastIndexOf("\n", start - 1) + 1;
  const block = body.slice(lineStart, end);
  const lines = block.split("\n").map((line, i) => (kind === "ordered" ? `${i + 1}. ` : prefix) + line);
  const replaced = lines.join("\n");
  const next = body.slice(0, lineStart) + replaced + body.slice(end);
  return { next, from: lineStart + replaced.length, to: lineStart + replaced.length };
}

const TOOLS = [
  ["h2", Heading2, "소제목"],
  ["bold", Bold, "굵게 (Ctrl+B)"],
  ["italic", Italic, "기울임 (Ctrl+I)"],
  ["list", List, "목록"],
  ["ordered", ListOrdered, "번호 목록"],
  ["quote", Quote, "인용문"],
  ["code", Code, "코드"],
];

// 노트 작성·수정 UI. 노트 초안도 이 편집기에 채운다(citations는 저장 시 그대로 보낸다).
// 패널에서는 작성/미리보기를 전환하고, "크게 쓰기"는 화면 전체에서 작성과 미리보기를 나란히 보여준다.
// 관련 노트 찾기: 저장 전 제목·본문으로만 검색하고 그 내용은 저장하지 않는다.
export function NoteEditor({
  initial,
  submitLabel = "저장",
  onSubmit,
  onCancel,
  citations = [],
  excludeNoteId,
  onOpenNote,
  extra,
}) {
  const [title, setTitle] = useState(initial?.title || ""),
    [body, setBody] = useState(initial?.body || ""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [tab, setTab] = useState("write"), // 패널: write | preview
    [wide, setWide] = useState(false);
  const [related, setRelated] = useState(null); // null | { loading, rows, error }
  const textRef = useRef(null),
    pending = useRef(null);

  // 서식 버튼·인용 삽입 뒤 커서를 바뀐 위치로 되돌린다.
  useEffect(() => {
    if (!pending.current || !textRef.current) return;
    const { from, to } = pending.current;
    pending.current = null;
    textRef.current.focus();
    textRef.current.setSelectionRange(from, to);
  }, [body]);

  // 본문 길이에 맞춰 입력칸 높이를 늘린다(크게 쓰기에서는 화면 높이를 채운다).
  useEffect(() => {
    const el = textRef.current;
    if (!el || wide) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 260), 640)}px`;
  }, [body, wide, tab]);

  useEffect(() => {
    if (!wide) return setTab("write"); // 패널로 돌아오면 이어서 쓸 수 있게 작성 탭을 연다
    const close = (e) => e.key === "Escape" && setWide(false);
    window.addEventListener("keydown", close);
    document.body.classList.add("modal-open");
    return () => {
      window.removeEventListener("keydown", close);
      document.body.classList.remove("modal-open");
    };
  }, [wide]);

  function format(kind) {
    const el = textRef.current;
    if (!el) return;
    const { next, from, to } = applyFormat(el, body, kind);
    pending.current = { from, to };
    setBody(next);
  }
  function insertCitation(id) {
    const el = textRef.current;
    const at = el ? el.selectionEnd : body.length;
    const token = `[${id}]`;
    pending.current = { from: at + token.length, to: at + token.length };
    setBody(body.slice(0, at) + token + body.slice(at));
  }
  function onKeyDown(e) {
    if (!(e.ctrlKey || e.metaKey)) return;
    if (e.key === "b" || e.key === "i") {
      e.preventDefault();
      format(e.key === "b" ? "bold" : "italic");
    } else if (e.key === "Enter") {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

  async function findRelated() {
    if (!title.trim() && !body.trim()) return;
    setRelated({ loading: true, rows: [], error: "" });
    try {
      const rows = await api.related({
        title: title.trim(),
        body,
        ...(excludeNoteId ? { exclude_note_id: excludeNoteId } : {}),
      });
      setRelated({ loading: false, rows: (rows || []).slice(0, 3), error: "" });
    } catch (e) {
      setRelated({ loading: false, rows: [], error: e.message });
    }
  }
  const used = new Set([...body.matchAll(/\[(c\d+)\]/g)].map((m) => m[1]));
  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || !body.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit({ title: title.trim(), body });
      setWide(false);
    } catch (err) {
      // 실패해도 입력 내용은 그대로 둔다.
      setError(err.message);
      setBusy(false);
    }
  }

  const showWrite = wide || tab === "write",
    showPreview = wide || tab === "preview";
  const editor = (
    <form className={`note-editor ${wide ? "wide" : ""}`} onSubmit={submit}>
      <div className="note-editor-top">
        <input
          aria-label="노트 제목"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="노트 제목"
          maxLength={200}
          required
        />
        <button
          type="button"
          className="icon-button"
          onClick={() => setWide(!wide)}
          aria-label={wide ? "패널로 돌아가기" : "크게 쓰기"}
          title={wide ? "패널로 돌아가기 (Esc)" : "크게 쓰기"}
        >
          {wide ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
      </div>
      <div className="md-toolbar" role="toolbar" aria-label="서식">
        {TOOLS.map(([kind, Icon, label]) => (
          <button
            key={kind}
            type="button"
            className="icon-button"
            onClick={() => format(kind)}
            disabled={!showWrite}
            aria-label={label}
            title={label}
          >
            <Icon size={15} />
          </button>
        ))}
        {!wide && (
          <div className="md-tabs" role="tablist" aria-label="보기">
            <button type="button" role="tab" aria-selected={tab === "write"} onClick={() => setTab("write")}>
              <PenLine size={13} />
              작성
            </button>
            <button type="button" role="tab" aria-selected={tab === "preview"} onClick={() => setTab("preview")}>
              <Eye size={13} />
              미리보기
            </button>
          </div>
        )}
        {wide && (
          <span className="md-split-label">
            <Columns2 size={13} />
            작성 · 미리보기
          </span>
        )}
      </div>
      <div className="note-editor-panes">
        {showWrite && (
          <textarea
            ref={textRef}
            aria-label="노트 본문"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={"Markdown으로 정리해 보세요.\n## 소제목, - 목록, **굵게** · Ctrl+Enter로 저장"}
            required
          />
        )}
        {showPreview && (
          <div className="note-editor-preview" aria-label="미리보기">
            {body.trim() ? (
              <NoteMarkdown body={body} citations={citations} />
            ) : (
              <p className="subtle-empty">본문을 쓰면 여기에 정리된 모양으로 보여요.</p>
            )}
          </div>
        )}
      </div>
      {!!citations.length && (
        <div className="draft-citations" aria-label="노트 인용">
          {citations.map((c) => (
            <button
              type="button"
              key={c.id}
              className={used.has(c.id) ? "" : "unused"}
              title={`${c.quote || c.title || ""}\n누르면 커서 위치에 [${c.id}]를 넣어요.`}
              onClick={() => insertCitation(c.id)}
              disabled={!showWrite}
            >
              [{c.id}] {c.source_type === "note" ? "내 노트" : `자료 ${c.page}페이지`}
            </button>
          ))}
          <small>누르면 본문에 넣어요. 본문에서 지운 [cN] 인용은 저장되지 않아요.</small>
        </div>
      )}
      <div className="related-box">
        <button
          type="button"
          className="text-button"
          onClick={findRelated}
          disabled={related?.loading || (!title.trim() && !body.trim())}
        >
          {related?.loading ? <LoaderCircle size={13} className="spin" /> : <Search size={13} />}
          관련 노트 찾기
        </button>
        {related && !related.loading && (
          <div className="related-list">
            <ErrorBox message={related.error} />
            {!related.error && !related.rows.length && (
              <p className="subtle-empty">관련된 이전 노트를 찾지 못했어요.</p>
            )}
            {related.rows.map((n) => (
              <div className="related-row" key={n.note_id}>
                <div>
                  <strong>{n.title}</strong>
                  {n.snippet && <p>{n.snippet}</p>}
                </div>
                {onOpenNote && (
                  <button type="button" className="text-button" onClick={() => onOpenNote(n.note_id)}>
                    열기
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
      {extra}
      <ErrorBox message={error} />
      <div className="note-editor-actions">
        {onCancel && (
          <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
            취소
          </button>
        )}
        <button className="primary" disabled={busy || !title.trim() || !body.trim()}>
          {busy ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}
          {busy ? "저장 중…" : submitLabel}
        </button>
      </div>
    </form>
  );
  if (!wide) return editor;
  return (
    <>
      <p className="note-editor-away" role="status">
        크게 쓰는 중이에요. <button type="button" className="text-button" onClick={() => setWide(false)}>패널로 돌아가기</button>
      </p>
      {createPortal(
        <div className="note-editor-overlay" role="dialog" aria-modal="true" aria-label="노트 크게 쓰기">
          {editor}
        </div>,
        document.body,
      )}
    </>
  );
}
