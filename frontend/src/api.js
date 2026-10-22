export const isMock = import.meta.env.VITE_USE_MOCK === "true";

// 상태 코드별 기본 안내. 서버가 문자열 detail을 주면 그 문구를 우선 표시한다.
const statusMessages = {
  400: "질문에 사용할 자료나 노트가 없습니다. PDF 처리가 끝났는지, 연결 노트가 있는지 확인해 주세요.",
  404: "요청한 항목을 찾을 수 없습니다. 화면을 새로고침해 주세요.",
  409: "이 채팅에서 답변을 만드는 중입니다. 답변이 끝난 뒤 다시 질문해 주세요.",
  422: "입력 내용을 확인해 주세요.",
  503: "답변 서비스에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
};
export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
const fail = (status, detail) =>
  new ApiError(
    status,
    typeof detail === "string" && detail
      ? detail
      : statusMessages[status] ||
        `요청을 처리하지 못했습니다 (${status}). 잠시 후 다시 시도해 주세요.`,
  );

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new ApiError(
      0,
      "서버에 연결할 수 없습니다. 백엔드 실행 상태를 확인한 뒤 다시 시도해 주세요.",
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw fail(response.status, data?.detail);
  return data;
}
const json = (value, method = "POST") => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});
const enc = encodeURIComponent;

const real = {
  list: () => request("/workspaces"),
  create: (value) => request("/workspaces", json(value)),
  detail: (id) => request(`/workspaces/${enc(id)}`),
  upload: (id, file) => {
    const body = new FormData();
    body.append("file", file);
    return request(`/workspaces/${enc(id)}/documents`, { method: "POST", body });
  },
  document: (id) => request(`/documents/${enc(id)}`),
  retry: (id) => request(`/documents/${enc(id)}/retry`, { method: "POST" }),
  // 호환용 워크스페이스 질문. 새 화면은 chatAsk를 사용한다.
  ask: (id, question, include_notes = true) =>
    request(`/workspaces/${enc(id)}/ask`, json({ question, include_notes })),
  // 채팅
  chats: (id) => request(`/workspaces/${enc(id)}/chats`),
  createChat: (id, title) =>
    request(`/workspaces/${enc(id)}/chats`, json(title ? { title } : {})),
  chat: (id) => request(`/chats/${enc(id)}`),
  messages: (id) => request(`/chats/${enc(id)}/messages`),
  chatAsk: (id, question, include_notes = true) =>
    request(`/chats/${enc(id)}/ask`, json({ question, include_notes })),
  // 답변·노트
  answers: (id) => request(`/workspaces/${enc(id)}/answers`),
  answer: (id) => request(`/answers/${enc(id)}`),
  draft: (id) => request(`/answers/${enc(id)}/note-draft`, { method: "POST" }),
  notes: (q = "", workspace_id = "") =>
    request(
      `/notes?${new URLSearchParams({ q, ...(workspace_id ? { workspace_id } : {}) })}`,
    ),
  note: (id) => request(`/notes/${enc(id)}`),
  saveNote: (id, value) =>
    request(id ? `/notes/${enc(id)}` : "/notes", json(value, id ? "PUT" : "POST")),
  linkNote: (workspace, note, linked) =>
    request(`/workspaces/${enc(workspace)}/notes/${enc(note)}`, {
      method: linked ? "POST" : "DELETE",
    }),
  related: (value) => request("/notes/related", json(value)),
};

// ---------------------------------------------------------------------------
// 목 모드: 브라우저 localStorage에만 저장하는 화면 미리보기. 백엔드 목 DB와 별개다.
// ---------------------------------------------------------------------------
const key = "studylink-preview-v1";
const readItems = (name) => {
  try {
    return JSON.parse(localStorage.getItem(name ? `${key}-${name}` : key)) || [];
  } catch {
    return [];
  }
};
const saveItems = (name, rows) => {
  try {
    localStorage.setItem(name ? `${key}-${name}` : key, JSON.stringify(rows));
  } catch {
    // 저장 불가(사생활 보호 모드 등)여도 현재 화면은 계속 동작한다.
  }
};
const read = () => readItems("");
const save = (rows) => saveItems("", rows);
const delay = (ms = 350) => new Promise((resolve) => setTimeout(resolve, ms));
const now = () => new Date().toISOString();
const notFound = (what) => new ApiError(404, `${what}을(를) 찾을 수 없습니다.`);
// 업로드한 PDF의 blob URL. 새로고침하면 사라지므로 그때는 자리표시 화면을 보여준다.
const blobUrls = new Map();
// 같은 채팅의 동시 질문을 409로 막기 위한 진행 중 표시(탭 안에서만 유효).
const inflight = new Set();

const noteSummary = ({ id, title, index_status, updated_at }) => ({
  id,
  title,
  index_status,
  updated_at,
});
// 1일차 목 답변(studylink-preview-v1-answers)을 워크스페이스별 "이전 대화"로 한 번만 옮긴다.
function migrateLegacy(workspaceId) {
  const chats = readItems("chats");
  if (chats.some((c) => c.workspace_id === workspaceId && c.legacy)) return;
  const old = readItems("answers")
    .filter((a) => a.workspace_id === workspaceId)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  if (!old.length) return;
  const chat = {
    id: crypto.randomUUID(),
    workspace_id: workspaceId,
    title: "이전 대화",
    created_at: old[0].created_at,
    updated_at: old.at(-1).created_at,
    legacy: true,
  };
  saveItems("chats", [...chats, chat]);
  saveItems("messages", [
    ...readItems("messages"),
    ...old.map((a) => ({ ...a, chat_id: chat.id })),
  ]);
}
const chatOut = ({ legacy, ...chat }) => chat;
const workspaceChats = (id) =>
  readItems("chats")
    .filter((c) => c.workspace_id === id)
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .map(chatOut);

const mock = {
  async list() {
    await delay();
    return read();
  },
  async create(value) {
    await delay();
    const row = {
      ...value,
      id: crypto.randomUUID(),
      created_at: now(),
      documents: [],
    };
    save([row, ...read()]);
    return row;
  },
  async detail(id) {
    await delay();
    const row = read().find((w) => w.id === id);
    if (!row) throw notFound("워크스페이스");
    migrateLegacy(id);
    return {
      ...row,
      notes: readItems("notes")
        .filter((n) => n.workspace_ids.includes(id))
        .map(noteSummary),
      chats: workspaceChats(id),
    };
  },
  async upload(id, file) {
    await delay();
    const rows = read();
    const workspace = rows.find((w) => w.id === id);
    if (!workspace) throw notFound("워크스페이스");
    const row = {
      id: crypto.randomUUID(),
      workspace_id: id,
      filename: file.name,
      status: "processing",
      page_count: null,
      error: null,
      started_at: Date.now(),
    };
    blobUrls.set(row.id, URL.createObjectURL(file));
    workspace.documents.push(row);
    save(rows);
    return row;
  },
  async document(id) {
    await delay();
    const rows = read();
    const doc = rows.flatMap((w) => w.documents).find((d) => d.id === id);
    if (!doc) throw notFound("자료");
    if (doc.status === "processing" && Date.now() - doc.started_at > 2500) {
      // 파일명에 "실패"가 있으면 첫 처리에서 실패 경로를 재현한다.
      if (doc.filename.includes("실패") && !doc.retried) {
        doc.status = "failed";
        doc.error = "목 모드: 처리 실패를 재현했습니다. 다시 처리하기를 눌러 보세요.";
      } else {
        doc.status = "ready";
        doc.page_count = 3;
      }
      save(rows);
    }
    return doc;
  },
  async retry(id) {
    const rows = read();
    const doc = rows.flatMap((w) => w.documents).find((d) => d.id === id);
    if (!doc) throw notFound("자료");
    Object.assign(doc, {
      status: "processing",
      error: null,
      retried: true,
      started_at: Date.now(),
    });
    save(rows);
    return doc;
  },
  async chats(id) {
    await delay();
    return workspaceChats(id);
  },
  async createChat(id, title) {
    await delay();
    if (!read().some((w) => w.id === id)) throw notFound("워크스페이스");
    const time = now();
    const chat = {
      id: crypto.randomUUID(),
      workspace_id: id,
      title: title || "새 채팅",
      created_at: time,
      updated_at: time,
    };
    saveItems("chats", [...readItems("chats"), chat]);
    return chat;
  },
  async chat(id) {
    await delay();
    const chat = readItems("chats").find((c) => c.id === id);
    if (!chat) throw notFound("채팅");
    return chatOut(chat);
  },
  async messages(id) {
    await delay();
    if (!readItems("chats").some((c) => c.id === id)) throw notFound("채팅");
    return readItems("messages")
      .filter((m) => m.chat_id === id)
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
  },
  async chatAsk(chatId, question, include_notes = true) {
    if (inflight.has(chatId))
      throw new ApiError(409, "이 채팅에서 답변을 만드는 중입니다. 답변이 끝난 뒤 다시 질문해 주세요.");
    const chat = readItems("chats").find((c) => c.id === chatId);
    if (!chat) throw notFound("채팅");
    inflight.add(chatId);
    try {
      await delay(1800);
      const workspace = read().find((w) => w.id === chat.workspace_id);
      const doc = workspace?.documents.find((d) => d.status === "ready");
      const note =
        include_notes &&
        readItems("notes").find(
          (n) => n.workspace_ids.includes(chat.workspace_id) && n.index_status === "ok",
        );
      if (!doc && !note)
        throw new ApiError(400, "검색할 자료나 연결 노트가 없습니다. PDF 처리가 끝난 뒤 질문해 주세요.");
      // 질문에 "서비스 오류"를 넣으면 503 경로를 재현한다.
      if (question.includes("서비스 오류"))
        throw new ApiError(503, "모델 서비스에 연결할 수 없습니다. 잠시 후 재시도하세요");
      const previous = readItems("messages").filter((m) => m.chat_id === chatId);
      const citations = [];
      if (doc) {
        const pages = doc.page_count || 1;
        const page = (previous.length % pages) + 1;
        citations.push({ id: "e1", source_type: "doc", document_id: doc.id, page, title: doc.filename, quote: `목 모드 발췌 · ${page}페이지. 실제 PDF 분석 결과가 아닙니다.` });
        if (pages > 1) {
          const other = (page % pages) + 1;
          citations.push({ id: "e2", source_type: "doc", document_id: doc.id, page: other, title: doc.filename, quote: `목 모드 발췌 · ${other}페이지. 같은 자료의 다른 페이지입니다.` });
        }
      }
      if (note)
        citations.push({ id: `e${citations.length + 1}`, source_type: "note", note_id: note.id, title: note.title, quote: note.body.slice(0, 200) });
      // 질문에 "근거 없음"을 넣으면 근거 부족 경로를 재현한다.
      const insufficient = question.includes("근거 없음");
      const context = previous.length
        ? `이 채팅의 ${previous.length + 1}번째 질문으로, 직전 질문 "${previous.at(-1).question.slice(0, 40)}"의 문맥을 이어받았습니다.`
        : "이 채팅의 첫 질문입니다. 다른 채팅의 대화는 참고하지 않습니다.";
      const answer = {
        answer_id: crypto.randomUUID(),
        status: insufficient ? "insufficient_evidence" : "grounded",
        segments: insufficient
          ? []
          : [
              { text: `화면 확인용 답변입니다. ${context}`, citation_ids: [citations[0].id] },
              { text: "워크스페이스의 공통 자료와 연결 노트를 근거로 표시합니다.", citation_ids: citations.slice(1).map((c) => c.id) },
            ],
        citations: insufficient ? [] : citations,
      };
      const time = now();
      saveItems("messages", [
        ...readItems("messages"),
        { ...answer, question, created_at: time, chat_id: chatId },
      ]);
      saveItems(
        "chats",
        readItems("chats").map((c) => (c.id === chatId ? { ...c, updated_at: time } : c)),
      );
      return answer;
    } finally {
      inflight.delete(chatId);
    }
  },
  async ask() {
    throw new ApiError(422, "목 모드에서는 채팅별 질문을 사용합니다.");
  },
  async answers(workspace) {
    await delay();
    const chatIds = workspaceChats(workspace).map((c) => c.id);
    return readItems("messages")
      .filter((m) => chatIds.includes(m.chat_id))
      .slice(-20)
      .reverse();
  },
  async answer(id) {
    await delay();
    const a = readItems("messages").find((m) => m.answer_id === id);
    if (!a) throw notFound("답변");
    return a;
  },
  async notes(q = "", workspace = "") {
    await delay();
    return readItems("notes")
      .filter(
        (n) =>
          n.title.toLowerCase().includes(q.toLowerCase()) &&
          (!workspace || n.workspace_ids.includes(workspace)),
      )
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  },
  async note(id) {
    await delay();
    const note = readItems("notes").find((n) => n.id === id);
    if (!note) throw notFound("노트");
    return note;
  },
  async saveNote(id, value) {
    await delay();
    if (!value.title?.trim() || !value.body?.trim())
      throw new ApiError(422, "노트 제목과 본문을 입력해 주세요.");
    const citations = value.citations || [];
    const ids = [...value.body.matchAll(/\[(c\d+)\]/g)].map((m) => m[1]);
    if (ids.some((cid) => !citations.some((c) => c.citation_id === cid)))
      throw new ApiError(422, "본문의 인용 표시와 연결된 원본이 없습니다. 인용 표시를 확인해 주세요.");
    const rows = readItems("notes"),
      old = rows.find((n) => n.id === id),
      time = now();
    if (id && !old) throw notFound("노트");
    const note = {
      ...value,
      citations: citations.filter((c) => ids.includes(c.citation_id)),
      workspace_ids: [...new Set(value.workspace_ids || old?.workspace_ids || [])],
      id: id || crypto.randomUUID(),
      created_at: old?.created_at || time,
      updated_at: time,
      // 본문에 "[색인 실패]"를 넣으면 색인 실패 경로를 재현한다.
      index_status: value.body.includes("[색인 실패]") ? "failed" : "ok",
    };
    saveItems("notes", [note, ...rows.filter((n) => n.id !== note.id)]);
    return note;
  },
  async linkNote(workspace, id, linked) {
    await delay();
    const rows = readItems("notes"),
      n = rows.find((n) => n.id === id);
    if (!n) throw notFound("노트");
    n.workspace_ids = linked
      ? [...new Set([...n.workspace_ids, workspace])]
      : n.workspace_ids.filter((w) => w !== workspace);
    saveItems("notes", rows);
    return n;
  },
  async draft(id) {
    const a = await mock.answer(id);
    if (a.status !== "grounded")
      throw new ApiError(422, "근거 부족 답변은 초안으로 만들 수 없습니다.");
    const citations = a.citations.map((c, i) => ({ citation_id: `c${i + 1}`, source_type: c.source_type, document_id: c.document_id, page: c.page, quote: c.quote, cited_note_id: c.note_id, title: c.title }));
    return { title: a.question, body: a.segments.map((s) => `${s.text} ${s.citation_ids.map((cid) => `[${citations[a.citations.findIndex((c) => c.id === cid)].citation_id}]`).join(" ")}`).join("\n\n"), citations, fallback: true };
  },
  async related({ title, body, exclude_note_id }) {
    await delay();
    const terms = `${title} ${body}`.toLowerCase().split(/\s+/).filter((t) => t.length > 1);
    return readItems("notes").filter((n) => n.id !== exclude_note_id && n.index_status === "ok" && terms.some((t) => `${n.title} ${n.body}`.toLowerCase().includes(t))).slice(0, 3).map((n) => ({ note_id: n.id, title: n.title, snippet: n.body.slice(0, 160) }));
  },
};

export const api = isMock ? mock : real;
export const pdfUrl = (id) => `/api/documents/${enc(id)}/file`;
// PDF 뷰어에 넣을 주소. 목 모드에서는 이번 탭에서 업로드한 파일만 열 수 있다(없으면 null).
export const viewerUrl = (id) => (isMock ? blobUrls.get(id) || null : pdfUrl(id));
