import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUp,
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileText,
  Layers,
  Link2,
  LoaderCircle,
  MessageSquare,
  NotebookPen,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  TriangleAlert,
  Unlink,
  Upload,
  X,
} from "lucide-react";
import { api, isMock, viewerUrl } from "./api";
import { ErrorBox, Spinner } from "./ui";
import "./workspace.css";

// 마지막으로 선택한 채팅은 워크스페이스별로 기억한다. 저장소를 못 써도 화면은 동작한다.
const lastChatKey = (id) => `studylink-last-chat-${id}`;
function readLastChat(id) {
  try {
    return localStorage.getItem(lastChatKey(id));
  } catch {
    return null;
  }
}
function writeLastChat(id, chatId) {
  try {
    localStorage.setItem(lastChatKey(id), chatId);
  } catch {
    // 무시: 다음 방문 때 가장 최근 채팅을 연다.
  }
}
const byUpdated = (a, b) => (b.updated_at || "").localeCompare(a.updated_at || "");
const NEW_DRAFT = "__new__";
function shortTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}
const noteSummary = ({ id, title, index_status, updated_at }) => ({
  id,
  title,
  index_status,
  updated_at,
});

export function Workspace() {
  const { id } = useParams();
  const [workspace, setWorkspace] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [pollError, setPollError] = useState("");
  // 채팅: 목록, 선택, 채팅별 기록·요청 상태, 채팅별 입력 초안
  const [chats, setChats] = useState([]),
    [activeId, setActiveId] = useState(null),
    [threads, setThreads] = useState({}),
    [drafts, setDrafts] = useState({}),
    [includeNotes, setIncludeNotes] = useState(true),
    [creating, setCreating] = useState(false),
    [chatError, setChatError] = useState("");
  // 공통 자원 패널: 채팅을 바꿔도 유지되는 워크스페이스 단위 상태
  const [viewer, setViewer] = useState(null),
    [tab, setTab] = useState("docs");
  const threadsRef = useRef(threads);
  threadsRef.current = threads;

  const patchThread = useCallback(
    (chatId, patch) =>
      setThreads((all) => {
        const current = all[chatId] || {};
        const next = typeof patch === "function" ? patch(current) : patch;
        return { ...all, [chatId]: { ...current, ...next } };
      }),
    [],
  );

  const load = () => {
    setError("");
    setLoading(true);
    api
      .detail(id)
      .then(async (row) => {
        let list = row.chats;
        if (!Array.isArray(list)) list = await api.chats(id).catch(() => []);
        list = [...list].sort(byUpdated);
        const last = readLastChat(id);
        setWorkspace(row);
        setChats(list);
        setActiveId(
          (current) =>
            list.find((c) => c.id === current)?.id ||
            list.find((c) => c.id === last)?.id ||
            list[0]?.id ||
            null,
        );
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const loadMessages = useCallback(
    (chatId) => {
      patchThread(chatId, { loading: true, error: "" });
      api
        .messages(chatId)
        .then((messages) =>
          patchThread(chatId, (t) => ({
            // 응답 대기 중 도착한 새 답변이 있으면 서버 목록 뒤에 보존한다.
            messages: [
              ...messages,
              ...(t.messages || []).filter(
                (m) => !messages.some((s) => s.answer_id === m.answer_id),
              ),
            ],
            loaded: true,
          })),
        )
        .catch((e) => patchThread(chatId, { error: e.message }))
        .finally(() => patchThread(chatId, { loading: false }));
    },
    [patchThread],
  );
  useEffect(() => {
    if (!activeId) return;
    writeLastChat(id, activeId);
    const t = threadsRef.current[activeId];
    if (!t?.loaded && !t?.loading) loadMessages(activeId);
  }, [id, activeId, loadMessages]);

  // 자료 처리 상태 폴링(1일차와 동일)
  const processing =
    workspace?.documents
      ?.filter((d) => d.status === "processing")
      .map((d) => d.id)
      .join(",") || "";
  useEffect(() => {
    if (!processing) return;
    let cancelled = false;
    let timer;
    async function poll() {
      const results = await Promise.allSettled(processing.split(",").map(api.document));
      if (cancelled) return;
      const updated = results.filter((r) => r.status === "fulfilled").map((r) => r.value);
      setWorkspace((w) => ({
        ...w,
        documents: w.documents.map((d) => updated.find((u) => u.id === d.id) || d),
      }));
      setPollError(
        results.some((r) => r.status === "rejected")
          ? "자료 상태를 확인하지 못했습니다. 연결이 복구되면 자동으로 다시 확인합니다."
          : "",
      );
      timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [processing]);

  async function createChat(title) {
    if (creating) return null;
    setCreating(true);
    setChatError("");
    try {
      const chat = await api.createChat(id, title);
      setChats((list) => [chat, ...list.filter((c) => c.id !== chat.id)].sort(byUpdated));
      patchThread(chat.id, { messages: [], loaded: true });
      setActiveId(chat.id);
      return chat;
    } catch (e) {
      setChatError(e.message);
      return null;
    } finally {
      setCreating(false);
    }
  }

  async function ask(e) {
    e?.preventDefault();
    const draftKey = activeId || NEW_DRAFT;
    const question = (drafts[draftKey] || "").trim();
    if (!question) return;
    let chatId = activeId;
    if (!chatId) {
      // 채팅이 하나도 없으면 첫 질문으로 채팅을 만든다.
      const chat = await createChat(question.slice(0, 30));
      if (!chat) return;
      chatId = chat.id;
    }
    if (threadsRef.current[chatId]?.pending) return;
    patchThread(chatId, { pending: question, askError: "" });
    setDrafts((d) => ({ ...d, [chatId]: "", [NEW_DRAFT]: "" }));
    try {
      const answer = await api.chatAsk(chatId, question, includeNotes);
      const time = new Date().toISOString();
      patchThread(chatId, (t) => ({
        messages: [
          ...(t.messages || []),
          { ...answer, question, created_at: time, chat_id: chatId },
        ],
        pending: null,
      }));
      setChats((list) =>
        list.map((c) => (c.id === chatId ? { ...c, updated_at: time } : c)).sort(byUpdated),
      );
    } catch (err) {
      patchThread(chatId, { pending: null, askError: err.message });
      // 실패한 질문은 다시 보낼 수 있게 입력창에 되돌린다.
      setDrafts((d) => ({ ...d, [chatId]: d[chatId] || question }));
    }
  }

  function openCitation(citation, from) {
    if (citation.source_type === "note") {
      const noteId = citation.note_id || citation.cited_note_id;
      if (noteId) setViewer({ kind: "note", note_id: noteId, from, nonce: Date.now() });
    } else if (citation.document_id) {
      setViewer({
        kind: "doc",
        document_id: citation.document_id,
        page: Number(citation.page) || 1,
        quote: citation.quote,
        from,
        nonce: Date.now(),
      });
    }
  }
  const refreshNotes = () =>
    api
      .notes("", id)
      .then((rows) => setWorkspace((w) => ({ ...w, notes: rows.map(noteSummary) })));

  if (loading) return <Spinner />;
  if (error)
    return (
      <div className="home">
        <Link to="/">← 워크스페이스</Link>
        <ErrorBox message={error} retry={load} />
      </div>
    );
  if (!workspace) return null;

  const docs = workspace.documents || [],
    notes = workspace.notes || [];
  const readyDocs = docs.filter((d) => d.status === "ready").length,
    searchableNotes = notes.filter((n) => n.index_status !== "failed").length;
  const canAsk = readyDocs > 0 || (includeNotes && searchableNotes > 0);
  const activeChat = chats.find((c) => c.id === activeId) || null;
  const thread = (activeId && threads[activeId]) || {};
  const draftKey = activeId || NEW_DRAFT;

  return (
    <div className="workspace-page">
      <Link className="back-link" to="/">
        <ArrowLeft size={15} />
        모든 워크스페이스
      </Link>
      <div className="workspace-heading">
        <span className="workspace-icon">
          <BookOpen size={24} />
        </span>
        <div>
          <h1>{workspace.title}</h1>
          <p>{workspace.goal || "자료를 읽고, 질문하며 배움을 연결해 보세요."}</p>
        </div>
      </div>
      <div className="chat-layout">
        <ChatList
          chats={chats}
          activeId={activeId}
          threads={threads}
          creating={creating}
          error={chatError}
          onSelect={setActiveId}
          onCreate={() => createChat(`새 채팅 ${chats.length + 1}`)}
        />
        <section className="conversation panel">
          <div className="panel-heading">
            <h2>
              <Sparkles size={18} />
              <span className="chat-title">{activeChat?.title || "새 채팅"}</span>
            </h2>
            <span className="scope-badge">
              자료 {readyDocs}개{includeNotes ? ` · 노트 ${searchableNotes}개` : ""} 검색
            </span>
          </div>
          <Thread
            key={activeId || "none"}
            thread={thread}
            hasChat={!!activeChat}
            docs={docs}
            viewer={viewer}
            onCitation={openCitation}
            onReload={() => loadMessages(activeId)}
          />
          <form className="question-form" onSubmit={ask}>
            <div className="question-input">
              <textarea
                aria-label="자료에 질문하기"
                value={drafts[draftKey] || ""}
                onChange={(e) => setDrafts((d) => ({ ...d, [draftKey]: e.target.value }))}
                placeholder={
                  thread.pending
                    ? "이 채팅의 답변을 만드는 중이에요. 다른 채팅에서는 계속 질문할 수 있어요."
                    : canAsk
                      ? "자료에 대해 무엇이 궁금한가요?"
                      : "자료 처리가 끝나거나 노트를 연결하면 질문할 수 있어요"
                }
                rows={2}
                maxLength={4000}
                disabled={!!thread.pending}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    if (canAsk) ask(e);
                  }
                }}
              />
              <button
                className="send-button"
                type="submit"
                disabled={!canAsk || !(drafts[draftKey] || "").trim() || !!thread.pending || creating}
                aria-label="질문 보내기"
              >
                {thread.pending ? <LoaderCircle className="spin" size={20} /> : <ArrowUp size={21} />}
              </button>
            </div>
            <div className="question-options">
              <label className="include-toggle">
                <input
                  type="checkbox"
                  checked={includeNotes}
                  onChange={(e) => setIncludeNotes(e.target.checked)}
                />
                연결 노트 포함
              </label>
              <small>답변은 학습을 돕는 설명입니다. 인용된 근거와 함께 확인하세요.</small>
            </div>
          </form>
        </section>
        <ResourcePanel
          workspace={workspace}
          setWorkspace={setWorkspace}
          pollError={pollError}
          viewer={viewer}
          setViewer={setViewer}
          tab={tab}
          setTab={setTab}
          refreshNotes={refreshNotes}
          openCitation={openCitation}
        />
      </div>
    </div>
  );
}

function ChatList({ chats, activeId, threads, creating, error, onSelect, onCreate }) {
  return (
    <aside className="chat-list panel" aria-label="채팅 목록">
      <div className="panel-heading">
        <h2>
          <MessageSquare size={18} />
          채팅
        </h2>
        <span className="count">{chats.length}</span>
      </div>
      <div className="chat-list-body">
        <button className="secondary new-chat" onClick={onCreate} disabled={creating}>
          {creating ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}
          새 채팅
        </button>
        <ErrorBox message={error} />
        {chats.map((chat) => (
          <button
            key={chat.id}
            className={`chat-item ${chat.id === activeId ? "active" : ""}`}
            aria-current={chat.id === activeId ? "true" : undefined}
            onClick={() => onSelect(chat.id)}
          >
            <strong>{chat.title || "새 채팅"}</strong>
            <small>
              {threads[chat.id]?.pending ? (
                <>
                  <LoaderCircle size={11} className="spin" />
                  답변 생성 중
                </>
              ) : (
                shortTime(chat.updated_at)
              )}
            </small>
          </button>
        ))}
        {!chats.length && (
          <p className="subtle-empty">
            아직 채팅이 없어요.
            <br />
            질문을 보내면 첫 채팅이 만들어져요.
          </p>
        )}
      </div>
    </aside>
  );
}

function Thread({ thread, hasChat, docs, viewer, onCitation, onReload }) {
  const endRef = useRef(null);
  const messages = thread.messages || [];
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages.length, thread.pending]);
  const empty = !messages.length && !thread.pending && !thread.askError;
  return (
    <div className="conversation-body" aria-live="polite">
      {thread.loading && !messages.length ? (
        <Spinner>대화 기록을 불러오는 중…</Spinner>
      ) : thread.error ? (
        <ErrorBox message={thread.error} retry={onReload} />
      ) : empty ? (
        <div className="question-empty">
          <span className="sparkle-tile">
            <Sparkles size={29} />
          </span>
          <h2>{hasChat ? "이 채팅에서 질문을 시작해 보세요" : "궁금한 점을 연결해 보세요"}</h2>
          <p>
            같은 채팅의 앞선 대화는 이어 묻는 맥락이 되고,
            <br />
            워크스페이스의 자료와 연결 노트는 모든 채팅에서 함께 써요.
          </p>
          <div className="question-tip">
            <Search size={16} />
            개념의 정의나 차이점을 구체적으로 질문해 보세요.
          </div>
        </div>
      ) : (
        <>
          {messages.map((m) => (
            <Turn
              key={m.answer_id || m.created_at}
              message={m}
              docs={docs}
              viewer={viewer}
              onCitation={onCitation}
            />
          ))}
          {thread.pending && (
            <>
              <div className="question-bubble">{thread.pending}</div>
              <Spinner>자료에서 근거를 찾고 있어요…</Spinner>
            </>
          )}
          <ErrorBox message={thread.askError} />
        </>
      )}
      <div ref={endRef} />
    </div>
  );
}

function citationLabel(c, docs) {
  if (c.source_type === "note") return c.title || "내 노트";
  return docs.find((d) => d.id === c.document_id)?.filename || c.title || "자료";
}

function Turn({ message, docs, viewer, onCitation }) {
  const citations = message.citations || [];
  const segments = (message.segments || [])
    .map((s) => ({
      ...s,
      citation_ids: (s.citation_ids || []).filter((cid) => citations.some((c) => c.id === cid)),
    }))
    .filter((s) => s.citation_ids.length);
  const open = (cid) =>
    onCitation(
      citations.find((c) => c.id === cid),
      `${message.answer_id}:${cid}`,
    );
  return (
    <div className="turn">
      <div className="question-bubble">{message.question}</div>
      <div className="answer">
        <div className="answer-label">
          <span className="mini-logo">
            <Layers size={16} />
          </span>
          StudyLink<span>{shortTime(message.created_at)} · 자료 기반 답변</span>
        </div>
        {message.status === "insufficient_evidence" || !segments.length ? (
          <div className="insufficient">
            <h3>자료에서 확인하지 못함</h3>
            <p>
              현재 자료와 연결 노트에서 질문에 답할 근거를 찾지 못했어요. 질문을 구체적으로
              바꾸거나 관련 자료를 추가해 보세요.
            </p>
          </div>
        ) : (
          <>
            {segments.map((s, i) => (
              <p className="answer-segment" key={i}>
                {s.text}{" "}
                <span className="inline-citations">
                  {s.citation_ids.map((cid) => (
                    <button key={cid} onClick={() => open(cid)} aria-label={`${cid} 근거 열기`}>
                      [{cid}]
                    </button>
                  ))}
                </span>
              </p>
            ))}
            <div className="citations-title">
              답변의 근거 <span>{citations.length}</span>
            </div>
            {citations.map((c) => (
              <button
                className={`citation-card ${viewer?.from === `${message.answer_id}:${c.id}` ? "selected" : ""}`}
                key={c.id}
                onClick={() => open(c.id)}
              >
                <span className="citation-number">{c.id}</span>
                <div>
                  <strong>
                    <span className={`source-badge ${c.source_type === "note" ? "note" : "doc"}`}>
                      {c.source_type === "note" ? "내 노트" : "자료"}
                    </span>
                    {citationLabel(c, docs)}
                    {c.source_type !== "note" && <em>{c.page}페이지</em>}
                  </strong>
                  <p>{c.quote}</p>
                </div>
                <ChevronRight size={16} />
              </button>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 공통 자원 패널: PDF 목록·업로드 / 연결 노트 / 새 노트, 그리고 열람 영역
// ---------------------------------------------------------------------------
function ResourcePanel({
  workspace,
  setWorkspace,
  pollError,
  viewer,
  setViewer,
  tab,
  setTab,
  refreshNotes,
  openCitation,
}) {
  const viewerRef = useRef(null);
  useEffect(() => {
    if (viewer) viewerRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [viewer?.nonce]);
  const docs = workspace.documents || [],
    notes = workspace.notes || [];
  return (
    <aside className="resources panel" aria-label="공통 자원">
      <div className="panel-heading">
        <h2>
          <BookOpen size={18} />
          공통 자원
        </h2>
        <span className="scope-badge">모든 채팅에서 사용</span>
      </div>
      {viewer && (
        <div className="viewer" ref={viewerRef}>
          {viewer.kind === "doc" ? (
            <DocViewer
              viewer={viewer}
              doc={docs.find((d) => d.id === viewer.document_id)}
              setViewer={setViewer}
            />
          ) : (
            <NotePreview
              key={viewer.note_id}
              noteId={viewer.note_id}
              nonce={viewer.nonce}
              workspaceId={workspace.id}
              setViewer={setViewer}
              refreshNotes={refreshNotes}
              openCitation={openCitation}
            />
          )}
        </div>
      )}
      <div className="resource-tabs" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "docs"}
          className={tab === "docs" ? "active" : ""}
          onClick={() => setTab("docs")}
        >
          <FileText size={14} />
          자료 <span>{docs.length}</span>
        </button>
        <button
          role="tab"
          aria-selected={tab === "notes"}
          className={tab === "notes" ? "active" : ""}
          onClick={() => setTab("notes")}
        >
          <NotebookPen size={14} />
          연결 노트 <span>{notes.length}</span>
        </button>
      </div>
      {tab === "docs" ? (
        <DocsTab
          workspace={workspace}
          setWorkspace={setWorkspace}
          pollError={pollError}
          viewer={viewer}
          setViewer={setViewer}
        />
      ) : (
        <NotesTab
          workspaceId={workspace.id}
          notes={notes}
          viewer={viewer}
          setViewer={setViewer}
          refreshNotes={refreshNotes}
        />
      )}
    </aside>
  );
}

function DocViewer({ viewer, doc, setViewer }) {
  const url = viewerUrl(viewer.document_id);
  const pages = doc?.page_count || null;
  const go = (page) => setViewer({ ...viewer, page, quote: null, from: null, nonce: Date.now() });
  return (
    <>
      <div className="viewer-head">
        <div>
          <span className="source-badge doc">자료</span>
          <strong>{doc?.filename || "자료"}</strong>
        </div>
        <button className="icon-button" aria-label="열람 닫기" onClick={() => setViewer(null)}>
          <X size={18} />
        </button>
      </div>
      <div className="page-nav">
        <button
          className="icon-button"
          aria-label="이전 페이지"
          disabled={viewer.page <= 1}
          onClick={() => go(viewer.page - 1)}
        >
          <ChevronLeft size={16} />
        </button>
        <span data-testid="viewer-page">
          {viewer.page}페이지{pages ? ` / ${pages}` : ""}
        </span>
        <button
          className="icon-button"
          aria-label="다음 페이지"
          disabled={!!pages && viewer.page >= pages}
          onClick={() => go(viewer.page + 1)}
        >
          <ChevronRight size={16} />
        </button>
        {url && (
          <a className="text-button" href={`${url}#page=${viewer.page}`} target="_blank" rel="noreferrer">
            새 탭 <ExternalLink size={12} />
          </a>
        )}
      </div>
      {viewer.quote && <blockquote className="viewer-quote">{viewer.quote}</blockquote>}
      {url ? (
        // 같은 PDF의 다른 페이지도 확실히 이동하도록 페이지·요청마다 다시 마운트한다.
        <iframe
          key={`${viewer.document_id}-${viewer.page}-${viewer.nonce}`}
          className="pdf-frame"
          src={`${url}#page=${viewer.page}`}
          title={`${doc?.filename || "PDF"} ${viewer.page}페이지`}
        />
      ) : (
        <div className="pdf-placeholder" key={`${viewer.document_id}-${viewer.page}-${viewer.nonce}`}>
          <FileText size={30} />
          <strong>{viewer.page}페이지</strong>
          <p>
            {isMock
              ? "목 모드에서는 이번 탭에서 업로드한 PDF만 화면에 표시해요. 새로고침 전 업로드한 파일은 다시 올려 주세요."
              : "PDF를 표시할 수 없습니다."}
          </p>
        </div>
      )}
    </>
  );
}

function NotePreview({ noteId, nonce, workspaceId, setViewer, refreshNotes, openCitation }) {
  const [note, setNote] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [editing, setEditing] = useState(false),
    [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState("");
  const load = () => {
    setLoading(true);
    setError("");
    api
      .note(noteId)
      .then(setNote)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, [noteId, nonce]);
  const linked = note?.workspace_ids?.includes(workspaceId);
  async function link() {
    setBusy(true);
    setActionError("");
    try {
      await api.linkNote(workspaceId, noteId, true);
      setNote((n) => ({ ...n, workspace_ids: [...(n.workspace_ids || []), workspaceId] }));
      await refreshNotes();
    } catch (e) {
      setActionError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function save(value) {
    const saved = await api.saveNote(noteId, {
      ...value,
      workspace_ids: note.workspace_ids || [],
      citations: note.citations || [],
    });
    setNote(saved);
    setEditing(false);
    refreshNotes().catch(() => {});
  }
  return (
    <>
      <div className="viewer-head">
        <div>
          <span className="source-badge note">내 노트</span>
          <strong>{note?.title || "노트"}</strong>
        </div>
        <button className="icon-button" aria-label="열람 닫기" onClick={() => setViewer(null)}>
          <X size={18} />
        </button>
      </div>
      {loading ? (
        <Spinner>노트를 여는 중…</Spinner>
      ) : error ? (
        <ErrorBox message={error} retry={load} />
      ) : editing ? (
        <NoteEditor
          initial={note}
          submitLabel="다시 저장"
          onSubmit={save}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <div className="note-preview">
          {note.index_status === "failed" && <IndexWarning />}
          {!linked && (
            <div className="note-unlinked">
              이 워크스페이스에 연결되지 않은 노트예요. 연결하면 질문 근거로 쓸 수 있어요.
              <button className="text-button" onClick={link} disabled={busy}>
                <Link2 size={13} />
                연결하기
              </button>
            </div>
          )}
          <ErrorBox message={actionError} />
          <div className="note-body">
            {note.body}
          </div>
          {!!note.citations?.length && (
            <div className="note-citations">
              <div className="citations-title">
                노트 인용 <span>{note.citations.length}</span>
              </div>
              {note.citations.map((c) => (
                <button
                  key={c.id || c.citation_id}
                  className="citation-card"
                  disabled={c.missing}
                  onClick={() =>
                    openCitation(
                      { ...c, note_id: c.cited_note_id || c.note_id },
                      `${noteId}:${c.id || c.citation_id}`,
                    )
                  }
                >
                  <span className="citation-number">{c.id || c.citation_id}</span>
                  <div>
                    <strong>
                      <span className={`source-badge ${c.source_type === "note" ? "note" : "doc"}`}>
                        {c.source_type === "note" ? "내 노트" : "자료"}
                      </span>
                      {c.missing ? "원본을 찾을 수 없음" : c.title || (c.source_type === "note" ? "노트" : "자료")}
                      {c.source_type !== "note" && c.page && <em>{c.page}페이지</em>}
                    </strong>
                    {c.quote && <p>{c.quote}</p>}
                  </div>
                  <ChevronRight size={16} />
                </button>
              ))}
            </div>
          )}
          <button className="text-button" onClick={() => setEditing(true)}>
            <Pencil size={13} />
            노트 수정
          </button>
        </div>
      )}
    </>
  );
}

function IndexWarning() {
  return (
    <div className="note-warning" role="status">
      <TriangleAlert size={14} />
      <span>
        <b>검색 제외</b> 색인에 실패해 질문 근거로 쓰이지 않아요. 내용을 확인하고 다시 저장해 주세요.
      </span>
    </div>
  );
}

function NoteEditor({ initial, submitLabel = "저장", onSubmit, onCancel }) {
  const [title, setTitle] = useState(initial?.title || ""),
    [body, setBody] = useState(initial?.body || ""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || !body.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit({ title: title.trim(), body });
    } catch (err) {
      // 실패해도 입력 내용은 그대로 둔다.
      setError(err.message);
      setBusy(false);
    }
  }
  return (
    <form className="note-editor" onSubmit={submit}>
      <input
        aria-label="노트 제목"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="노트 제목"
        maxLength={200}
        required
      />
      <textarea
        aria-label="노트 본문"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="Markdown으로 정리해 보세요."
        rows={7}
        required
      />
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
}

function DocsTab({ workspace, setWorkspace, pollError, viewer, setViewer }) {
  const [uploading, setUploading] = useState(false),
    [uploadError, setUploadError] = useState(""),
    [retrying, setRetrying] = useState(null);
  const fileRef = useRef(null);
  const docs = workspace.documents || [];
  async function upload(file) {
    if (!file || uploading) return;
    setUploadError("");
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("PDF 자료만 업로드할 수 있습니다.");
      return;
    }
    setUploading(true);
    try {
      const doc = await api.upload(workspace.id, file);
      setWorkspace((w) => ({ ...w, documents: [...w.documents, doc] }));
    } catch (e) {
      setUploadError(e.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }
  async function retry(docId) {
    setRetrying(docId);
    setUploadError("");
    try {
      const doc = await api.retry(docId);
      setWorkspace((w) => ({
        ...w,
        documents: w.documents.map((d) => (d.id === docId ? doc : d)),
      }));
    } catch (e) {
      setUploadError(e.message);
    } finally {
      setRetrying(null);
    }
  }
  return (
    <div className="resource-body" role="tabpanel">
      <div
        className="upload-zone compact"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          upload(e.dataTransfer.files[0]);
        }}
      >
        <Upload size={20} />
        <span>텍스트 PDF를 끌어 놓거나 선택하세요</span>
        <button className="secondary" disabled={uploading} onClick={() => fileRef.current?.click()}>
          {uploading ? (
            <>
              <LoaderCircle className="spin" size={15} />
              업로드 중…
            </>
          ) : (
            <>
              <Plus size={15} />
              자료 선택
            </>
          )}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf,.pdf"
          onChange={(e) => upload(e.target.files[0])}
          hidden
        />
      </div>
      <ErrorBox message={uploadError} />
      <ErrorBox message={pollError} />
      <div className="document-list">
        {docs.map((doc) => (
          <div
            className={`document ${viewer?.kind === "doc" && viewer.document_id === doc.id ? "open" : ""}`}
            key={doc.id}
          >
            <div className="document-top">
              <span className="pdf-icon">
                <FileText size={18} />
              </span>
              <div>
                <strong>{doc.filename}</strong>
                <small>{doc.page_count ? `${doc.page_count}페이지 · PDF` : "PDF 자료"}</small>
              </div>
            </div>
            <div className="document-actions">
              <div className={`status ${doc.status}`}>
                {doc.status === "ready" ? (
                  <>
                    <Check size={13} />
                    질문 가능
                  </>
                ) : doc.status === "processing" ? (
                  <>
                    <LoaderCircle size={13} className="spin" />
                    자료 분석 중
                  </>
                ) : (
                  "처리 실패"
                )}
              </div>
              {doc.status === "ready" && (
                <button
                  className="text-button"
                  onClick={() =>
                    setViewer({ kind: "doc", document_id: doc.id, page: 1, nonce: Date.now() })
                  }
                >
                  원문 열기
                </button>
              )}
            </div>
            {doc.status === "failed" && (
              <>
                <p className="document-error">{doc.error || "자료를 처리하지 못했습니다."}</p>
                <button
                  className="text-button"
                  disabled={retrying === doc.id}
                  onClick={() => retry(doc.id)}
                >
                  <RefreshCw size={13} />
                  {retrying === doc.id ? "재시도 중…" : "다시 처리하기"}
                </button>
              </>
            )}
          </div>
        ))}
        {!docs.length && <p className="subtle-empty">추가한 자료가 여기에 표시됩니다.</p>}
      </div>
      <div className="materials-note">
        <BookOpen size={15} />
        <span>처리 완료된 자료만 답변의 근거로 사용해요. 모든 채팅이 같은 자료를 함께 써요.</span>
      </div>
    </div>
  );
}

function NotesTab({ workspaceId, notes, viewer, setViewer, refreshNotes }) {
  // 열려 있는 노트의 연결 상태가 바뀌면 미리보기를 다시 불러온다.
  const touchNote = (noteId) =>
    setViewer((v) => (v?.kind === "note" && v.note_id === noteId ? { ...v, nonce: Date.now() } : v));
  const [mode, setMode] = useState(null), // null | "link" | "new"
    [busy, setBusy] = useState(null),
    [error, setError] = useState("");
  async function unlink(noteId) {
    setBusy(noteId);
    setError("");
    try {
      await api.linkNote(workspaceId, noteId, false);
      await refreshNotes();
      touchNote(noteId);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }
  async function create(value) {
    const note = await api.saveNote(null, { ...value, workspace_ids: [workspaceId], citations: [] });
    setMode(null);
    refreshNotes().catch(() => {});
    setViewer({ kind: "note", note_id: note.id, nonce: Date.now() });
  }
  return (
    <div className="resource-body" role="tabpanel">
      <div className="note-actions">
        <button
          className={`secondary ${mode === "link" ? "pressed" : ""}`}
          onClick={() => setMode(mode === "link" ? null : "link")}
        >
          <Link2 size={14} />
          기존 노트 연결
        </button>
        <button
          className={`secondary ${mode === "new" ? "pressed" : ""}`}
          onClick={() => setMode(mode === "new" ? null : "new")}
        >
          <Plus size={14} />
          새 노트 작성
        </button>
      </div>
      {mode === "link" && (
        <LinkPicker
          workspaceId={workspaceId}
          linked={notes}
          refreshNotes={refreshNotes}
          onLinked={touchNote}
        />
      )}
      {mode === "new" && (
        <div className="note-new">
          <NoteEditor submitLabel="저장하고 연결" onSubmit={create} onCancel={() => setMode(null)} />
        </div>
      )}
      <ErrorBox message={error} />
      <div className="note-list">
        {notes.map((n) => (
          <div
            key={n.id}
            className={`note-item ${viewer?.kind === "note" && viewer.note_id === n.id ? "open" : ""}`}
          >
            <button
              className="note-open"
              onClick={() => setViewer({ kind: "note", note_id: n.id, nonce: Date.now() })}
            >
              <NotebookPen size={15} />
              <span>
                <strong>{n.title}</strong>
                <small>
                  {n.index_status === "failed" ? (
                    <em className="failed">검색 제외 · 다시 저장 필요</em>
                  ) : n.index_status === "ok" ? (
                    "검색 포함"
                  ) : (
                    n.index_status || ""
                  )}
                  {n.updated_at ? ` · ${shortTime(n.updated_at)}` : ""}
                </small>
              </span>
            </button>
            <button
              className="icon-button"
              aria-label={`${n.title} 연결 해제`}
              title="연결 해제(노트는 삭제되지 않아요)"
              disabled={busy === n.id}
              onClick={() => unlink(n.id)}
            >
              {busy === n.id ? <LoaderCircle size={15} className="spin" /> : <Unlink size={15} />}
            </button>
          </div>
        ))}
        {!notes.length && (
          <p className="subtle-empty">
            연결한 노트가 없어요.
            <br />
            기존 노트를 연결하거나 새로 작성해 보세요.
          </p>
        )}
      </div>
      <div className="materials-note">
        <NotebookPen size={15} />
        <span>연결 해제는 노트를 삭제하지 않아요. 이 워크스페이스의 검색 범위에서만 빠져요.</span>
      </div>
    </div>
  );
}

function LinkPicker({ workspaceId, linked, refreshNotes, onLinked }) {
  const [q, setQ] = useState(""),
    [rows, setRows] = useState([]),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .notes(q.trim())
        .then((list) => !cancelled && (setRows(list), setError("")))
        .catch((e) => !cancelled && setError(e.message))
        .finally(() => !cancelled && setLoading(false));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [q]);
  const candidates = rows.filter((n) => !linked.some((l) => l.id === n.id));
  async function link(noteId) {
    setBusy(noteId);
    setError("");
    try {
      await api.linkNote(workspaceId, noteId, true);
      await refreshNotes();
      onLinked(noteId);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="link-picker">
      <div className="search-input">
        <Search size={14} />
        <input
          aria-label="노트 제목 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="전체 노트에서 제목 검색"
        />
      </div>
      <ErrorBox message={error} />
      {loading ? (
        <Spinner>노트를 찾는 중…</Spinner>
      ) : candidates.length ? (
        candidates.map((n) => (
          <div className="link-row" key={n.id}>
            <span>{n.title}</span>
            <button className="text-button" disabled={busy === n.id} onClick={() => link(n.id)}>
              {busy === n.id ? <LoaderCircle size={13} className="spin" /> : <Link2 size={13} />}
              연결
            </button>
          </div>
        ))
      ) : (
        <p className="subtle-empty">연결할 수 있는 다른 노트가 없어요.</p>
      )}
    </div>
  );
}
