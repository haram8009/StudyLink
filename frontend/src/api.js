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

async function request(path, options = {}, messages = {}) {
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
  if (!response.ok) {
    // 화면별 상태 코드 문구(퀴즈 등)는 서버가 문자열 detail을 주지 않을 때만 쓴다.
    const detail = data?.detail;
    throw fail(
      response.status,
      typeof detail === "string" && detail ? detail : messages[response.status],
    );
  }
  return data;
}
const json = (value, method = "POST") => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(value),
});
const enc = encodeURIComponent;
export const quizMessages = {
  400: "출제할 자료가 없습니다. PDF를 올리고 처리가 끝난 뒤 다시 만들어 주세요.",
  409: "이 워크스페이스의 퀴즈를 만드는 중입니다. 끝난 뒤 다시 시도해 주세요.",
  422: "자료에서 문항을 하나도 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
  503: "문항을 만드는 모델 서비스에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
};
const submitMessages = {
  422: "모든 문항에 답했는지 확인해 주세요. 제출 내용은 저장되지 않았습니다.",
};
export const draftMessages = {
  422: "근거가 부족한 답변은 노트 초안으로 만들 수 없습니다.",
  503: "초안을 만드는 서비스에 일시적으로 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.",
};

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
  // 인용문이 PDF 쪽의 어디에 있는지(PDF 포인트, 왼쪽 위 기준). 쪽 텍스트는 URL에 넣지 않는다.
  highlight: (id, page, quote) => request(`/documents/${enc(id)}/highlight`, json({ page, quote })),
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
  draft: (id) =>
    request(`/answers/${enc(id)}/note-draft`, { method: "POST" }, draftMessages),
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
  // 3일차: 퀴즈·오답
  createQuiz: (id, count = 5) =>
    request(`/workspaces/${enc(id)}/quizzes`, json({ count }), quizMessages),
  quizzes: (id) => request(`/workspaces/${enc(id)}/quizzes`),
  quiz: (id) => request(`/quizzes/${enc(id)}`),
  submitQuiz: (id, answers) =>
    request(`/quizzes/${enc(id)}/submit`, json({ answers }), submitMessages),
  reviews: (workspace_id, status = "") =>
    request(`/reviews?${new URLSearchParams({ workspace_id, ...(status ? { status } : {}) })}`),
  review: (id) => request(`/reviews/${enc(id)}`),
  updateReview: (id, value) => request(`/reviews/${enc(id)}`, json(value, "PATCH")),
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
    // 실제 백엔드와 같은 인용 형식 {id:'cN', source_type, document_id, page, quote, note_id}.
    // 2일차 목 데이터의 citation_id·cited_note_id도 읽는다.
    const citations = (value.citations || []).map((c) => ({
      ...c,
      id: c.id || c.citation_id,
      note_id: c.note_id || c.cited_note_id || null,
    }));
    const ids = [...value.body.matchAll(/\[(c\d+)\]/g)].map((m) => m[1]);
    if (ids.some((cid) => !citations.some((c) => c.id === cid)))
      throw new ApiError(422, "본문의 인용 표시와 연결된 원본이 없습니다. 인용 표시를 확인해 주세요.");
    const rows = readItems("notes"),
      old = rows.find((n) => n.id === id),
      time = now();
    if (id && !old) throw notFound("노트");
    if (citations.some((c) => c.source_type === "note" && c.note_id && c.note_id === id))
      throw new ApiError(422, "노트는 자기 자신을 인용할 수 없습니다");
    const docs = read().flatMap((w) => w.documents);
    const note = {
      ...value,
      citations: citations
        .filter((c) => ids.includes(c.id))
        .map(({ citation_id, cited_note_id, missing, ...c }) => ({
          ...c,
          title:
            c.source_type === "note"
              ? rows.find((n) => n.id === c.note_id)?.title || c.title || ""
              : docs.find((d) => d.id === c.document_id)?.filename || c.title || "",
        })),
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
  // 노트 초안: 원 답변 인용만 [eN]→[cN]으로 옮긴다. 질문에 "요약 실패"가 있으면 fallback 경로.
  async draft(id) {
    await delay(900);
    const a = readItems("messages").find((m) => m.answer_id === id);
    if (!a) throw notFound("답변");
    if (a.status !== "grounded" || !a.segments?.length)
      throw new ApiError(422, "근거가 부족한 답변은 노트 초안으로 만들 수 없습니다.");
    const used = [...new Set(a.segments.flatMap((s) => s.citation_ids))];
    const map = Object.fromEntries(used.map((eid, i) => [eid, `c${i + 1}`]));
    const citations = used
      .map((eid) => a.citations.find((c) => c.id === eid))
      .filter(Boolean)
      .map((c) => ({
        id: map[c.id],
        source_type: c.source_type,
        document_id: c.source_type === "doc" ? c.document_id : null,
        page: c.source_type === "doc" ? c.page : null,
        quote: c.quote || "",
        note_id: c.source_type === "note" ? c.note_id : null,
      }));
    const marks = (s) => s.citation_ids.map((eid) => `[${map[eid]}]`).join("");
    const fallback = a.question.includes("요약 실패");
    return fallback
      ? {
          title: a.question.slice(0, 60),
          body: a.segments.map((s) => `${s.text} ${marks(s)}`).join("\n\n"),
          citations,
          fallback: true,
        }
      : {
          title: `${a.question.replace(/[?？]$/, "").slice(0, 50)} 정리`,
          body: `## 핵심\n${a.segments.map((s) => `- ${s.text.replace(/^화면 확인용 답변입니다\.\s*/, "")} ${marks(s)}`).join("\n")}\n\n(목 모드 요약 초안)`,
          citations,
          fallback: false,
        };
  },
  // 목 모드는 서버 PyMuPDF가 없어 하이라이트 위치를 계산하지 않는다(인용문 블록만 보인다).
  async highlight(_id, page) {
    return { page, width: 0, height: 0, rects: [] };
  },
  async related({ title, body, exclude_note_id }) {
    await delay();
    return mockRelated(`${title} ${body}`, exclude_note_id);
  },
  // ------------------------------- 3일차: 퀴즈 -------------------------------
  async createQuiz(workspaceId, count = 5) {
    if (quizInflight.has(workspaceId)) throw new ApiError(409, quizMessages[409]);
    quizInflight.add(workspaceId);
    try {
      await delay(2200);
      const workspace = read().find((w) => w.id === workspaceId);
      if (!workspace) throw notFound("워크스페이스");
      const ready = workspace.documents.filter((d) => d.status === "ready");
      if (!ready.length)
        throw new ApiError(400, "출제할 처리 완료 자료가 없습니다. PDF를 올리고 처리가 끝난 뒤 다시 만들어 주세요.");
      const scenario = mockQuizScenario;
      if (scenario === "unavailable")
        throw new ApiError(503, "모델 서비스에 연결할 수 없습니다. 잠시 후 재시도하세요");
      if (scenario === "zero")
        throw new ApiError(422, "유효한 문항을 하나도 만들지 못했습니다. 다시 시도해 주세요.");
      const requested = Math.min(5, Math.max(1, Number(count) || 5));
      const actual = scenario === "partial" ? Math.min(3, requested) : requested;
      const offset = readItems("quizzes").filter((q) => q.workspace_id === workspaceId).length;
      const questions = Array.from({ length: actual }, (_, i) => {
        const bank = QUESTION_BANK[(i + offset) % QUESTION_BANK.length];
        const doc = ready[i % ready.length];
        const pages = doc.page_count || 3;
        const page = ((i + offset) % pages) + 1;
        const options = shuffle([bank.answer, ...bank.wrong]).map((text) => ({
          option_id: crypto.randomUUID().slice(0, 8),
          text,
        }));
        const missing = scenario === "missing_doc" && i === 0;
        return {
          question_id: crypto.randomUUID(),
          stem: bank.stem,
          options,
          document_id: missing ? "deleted-document" : doc.id,
          filename: missing ? "삭제된 자료.pdf" : doc.filename,
          page,
          answer_option_id: options.find((o) => o.text === bank.answer).option_id,
          explanation: bank.explanation,
          quote: `목 모드 발췌 · ${page}페이지. ${bank.quote}`,
        };
      });
      const quiz = {
        quiz_id: crypto.randomUUID(),
        workspace_id: workspaceId,
        requested_count: requested,
        actual_count: actual,
        created_at: now(),
        submitted_at: null,
        score: null,
        questions,
        attempts: null,
      };
      saveItems("quizzes", [...readItems("quizzes"), quiz]);
      return quizPublic(quiz);
    } finally {
      quizInflight.delete(workspaceId);
    }
  },
  async quizzes(workspaceId) {
    await delay();
    if (!read().some((w) => w.id === workspaceId)) throw notFound("워크스페이스");
    return readItems("quizzes")
      .filter((q) => q.workspace_id === workspaceId)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, 20)
      .map(({ quiz_id, requested_count, actual_count, created_at, submitted_at, score }) => ({
        quiz_id,
        requested_count,
        actual_count,
        created_at,
        submitted_at,
        score,
      }));
  },
  async quiz(id) {
    await delay();
    const quiz = readItems("quizzes").find((q) => q.quiz_id === id);
    if (!quiz) throw notFound("퀴즈");
    return quiz.submitted_at ? quizGraded(quiz) : quizPublic(quiz);
  },
  async submitQuiz(id, answers) {
    await delay(600);
    const rows = readItems("quizzes");
    const quiz = rows.find((q) => q.quiz_id === id);
    if (!quiz) throw notFound("퀴즈");
    // 이미 제출한 퀴즈는 다시 채점하지 않고 저장된 결과를 돌려준다.
    if (quiz.submitted_at) return quizGraded(quiz);
    const keys = Object.keys(answers || {});
    const valid =
      keys.length === quiz.questions.length &&
      quiz.questions.every((q) => q.options.some((o) => o.option_id === answers[q.question_id]));
    if (!valid)
      throw new ApiError(422, "모든 문항에 이 퀴즈의 선택지로 답해야 합니다. 제출 내용은 저장되지 않았습니다.");
    quiz.attempts = { ...answers };
    quiz.submitted_at = now();
    quiz.score = quiz.questions.filter((q) => answers[q.question_id] === q.answer_option_id).length;
    const reviews = readItems("reviews");
    for (const q of quiz.questions) {
      if (answers[q.question_id] === q.answer_option_id) continue;
      if (reviews.some((r) => r.question_id === q.question_id)) continue;
      reviews.push({
        review_id: crypto.randomUUID(),
        workspace_id: quiz.workspace_id,
        quiz_id: quiz.quiz_id,
        question_id: q.question_id,
        status: "open",
        learner_reason: "",
        created_at: quiz.submitted_at,
      });
    }
    saveItems("quizzes", rows);
    saveItems("reviews", reviews);
    return quizGraded(quiz);
  },
  // ------------------------------- 3일차: 오답 -------------------------------
  async reviews(workspaceId, status = "") {
    await delay();
    return readItems("reviews")
      .filter((r) => r.workspace_id === workspaceId && (!status || r.status === status))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map(reviewOut)
      .filter(Boolean);
  },
  async review(id) {
    await delay(500);
    const row = readItems("reviews").find((r) => r.review_id === id);
    const out = row && reviewOut(row);
    if (!out) throw notFound("오답");
    const answer = out.options.find((o) => o.option_id === out.answer_option_id)?.text || "";
    const notes = readItems("notes");
    return {
      ...out,
      related_notes: mockRelated(`${out.stem} ${answer}`).map((n) => ({
        ...n,
        linked: !!notes.find((x) => x.id === n.note_id)?.workspace_ids.includes(row.workspace_id),
      })),
    };
  },
  async updateReview(id, value) {
    await delay();
    const rows = readItems("reviews");
    const row = rows.find((r) => r.review_id === id);
    if (!row) throw notFound("오답");
    if (value.learner_reason != null && value.learner_reason.length > 2000)
      throw new ApiError(422, "틀린 이유 메모는 2,000자 이하로 써 주세요.");
    if (value.status != null && !["open", "reviewed"].includes(value.status))
      throw new ApiError(422, "상태는 open 또는 reviewed만 가능합니다.");
    if (value.learner_reason != null) row.learner_reason = value.learner_reason;
    if (value.status != null) row.status = value.status;
    saveItems("reviews", rows);
    return reviewOut(row);
  },
};

// 목 퀴즈 시나리오(화면의 목 전용 선택 상자에서 바꾼다): normal | partial | zero | unavailable | missing_doc
let mockQuizScenario = "normal";
export const setMockQuizScenario = (value) => {
  mockQuizScenario = value;
};
const quizInflight = new Set();
function shuffle(list) {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
const publicQuestion = ({ question_id, stem, options, document_id, filename, page }) => ({
  question_id,
  stem,
  options,
  document_id,
  filename,
  page,
});
const quizPublic = (q) => ({
  quiz_id: q.quiz_id,
  workspace_id: q.workspace_id,
  requested_count: q.requested_count,
  actual_count: q.actual_count,
  created_at: q.created_at,
  submitted_at: null,
  questions: q.questions.map(publicQuestion),
});
const quizGraded = (q) => ({
  quiz_id: q.quiz_id,
  score: q.score,
  total: q.questions.length,
  submitted_at: q.submitted_at,
  questions: q.questions.map((x) => ({
    ...publicQuestion(x),
    selected_option_id: q.attempts[x.question_id],
    answer_option_id: x.answer_option_id,
    correct: q.attempts[x.question_id] === x.answer_option_id,
    explanation: x.explanation,
    quote: x.quote,
  })),
});
function reviewOut(row) {
  const quiz = readItems("quizzes").find((q) => q.quiz_id === row.quiz_id);
  const q = quiz?.questions.find((x) => x.question_id === row.question_id);
  if (!q) return null;
  return {
    review_id: row.review_id,
    quiz_id: row.quiz_id,
    question_id: row.question_id,
    stem: q.stem,
    selected_option_id: quiz.attempts?.[q.question_id] || null,
    answer_option_id: q.answer_option_id,
    options: q.options,
    explanation: q.explanation,
    document_id: q.document_id,
    filename: q.filename,
    page: q.page,
    quote: q.quote,
    status: row.status,
    learner_reason: row.learner_reason,
    created_at: row.created_at,
  };
}
// 관련 노트 목: 색인 성공 노트 중 두 글자 이상 단어가 겹치는 순으로 최대 3개.
function mockRelated(text, excludeId) {
  const terms = [
    ...new Set(
      text
        .toLowerCase()
        .split(/[\s.,?!()"'·:\-[\]#]+/)
        .filter((t) => t.length > 1),
    ),
  ];
  return readItems("notes")
    .filter((n) => n.id !== excludeId && n.index_status === "ok")
    .map((n) => {
      const hay = `${n.title} ${n.body}`.toLowerCase();
      return { n, hits: terms.filter((t) => hay.includes(t)).length };
    })
    .filter((x) => x.hits > 0)
    .sort((a, b) => b.hits - a.hits)
    .slice(0, 3)
    .map(({ n }) => ({ note_id: n.id, title: n.title, snippet: n.body.slice(0, 160) }));
}
const QUESTION_BANK = [
  {
    stem: "Residual connection(잔차 연결)을 쓰는 주된 이유로 가장 알맞은 것은?",
    answer: "깊은 층에서도 기울기 소실을 줄여 학습을 안정시키기 위해",
    wrong: ["모델의 파라미터 수를 절반으로 줄이기 위해", "입력 토큰의 순서 정보를 더하기 위해", "어텐션 가중치를 0으로 만들기 위해"],
    explanation: "잔차 연결은 입력을 출력에 더해 기울기가 지름길로 흐르게 하므로 깊은 신경망에서도 기울기 소실이 줄어든다.",
    quote: "Residual connection은 층의 입력을 출력에 더해 기울기 흐름을 돕는다.",
  },
  {
    stem: "기울기 소실(vanishing gradient) 문제에 대한 설명으로 옳은 것은?",
    answer: "역전파 중 기울기가 층을 지날수록 작아져 앞쪽 층이 거의 학습되지 않는다",
    wrong: ["학습률이 클수록 항상 해결된다", "출력층의 가중치만 커지는 현상이다", "데이터가 많으면 발생하지 않는다"],
    explanation: "시그모이드 같은 활성화 함수의 작은 미분값이 곱해지며 앞쪽 층의 기울기가 0에 가까워진다.",
    quote: "층이 깊어질수록 역전파되는 기울기가 지수적으로 작아질 수 있다.",
  },
  {
    stem: "Self-attention에서 Query·Key의 내적을 √d로 나누는 이유는?",
    answer: "내적 값이 커져 softmax가 한쪽으로 쏠리는 것을 막기 위해",
    wrong: ["계산 속도를 높이기 위해", "Value 벡터의 차원을 맞추기 위해", "위치 정보를 더하기 위해"],
    explanation: "차원이 크면 내적의 분산이 커져 softmax 기울기가 작아지므로 √d로 스케일링한다.",
    quote: "Scaled dot-product attention은 내적을 √d_k로 나눈다.",
  },
  {
    stem: "서브워드 토큰화(BPE 등)의 장점으로 가장 알맞은 것은?",
    answer: "처음 보는 단어도 더 작은 단위로 나누어 표현할 수 있다",
    wrong: ["문장 길이와 무관하게 토큰 수가 항상 같다", "어휘 사전이 필요 없다", "모든 단어를 한 글자씩 처리한다"],
    explanation: "자주 나오는 문자 조합을 단위로 삼아 미등록 단어(OOV)도 조각으로 표현한다.",
    quote: "BPE는 빈도가 높은 문자 쌍을 반복해서 병합한다.",
  },
  {
    stem: "단어 임베딩에 대한 설명으로 옳은 것은?",
    answer: "의미가 비슷한 단어가 벡터 공간에서 가깝게 놓이도록 학습한 밀집 벡터다",
    wrong: ["단어마다 하나의 1만 표시하는 희소 벡터다", "문장 길이를 나타내는 정수다", "학습 없이 사전 순서로 정해진다"],
    explanation: "임베딩은 저차원 밀집 벡터로, 문맥에서 함께 나오는 단어가 가깝게 학습된다.",
    quote: "임베딩은 단어를 의미를 담은 연속 벡터로 표현한다.",
  },
];

export const api = isMock ? mock : real;
// 목 모드 수동 검증용(재제출·409 등 화면에서 직접 만들 수 없는 요청). 실제 모드에서는 노출하지 않는다.
if (isMock && typeof window !== "undefined") window.studylinkMock = mock;
export const pdfUrl = (id) => `/api/documents/${enc(id)}/file`;
// PDF 뷰어에 넣을 주소. 목 모드에서는 이번 탭에서 업로드한 파일만 열 수 있다(없으면 null).
export const viewerUrl = (id) => (isMock ? blobUrls.get(id) || null : pdfUrl(id));
