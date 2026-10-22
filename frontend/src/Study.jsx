// 3일차: 퀴즈·오답노트 화면. 퀴즈와 오답은 워크스페이스 단위이며 채팅과 무관하다.
// 근거 페이지와 관련 노트는 2일차 공통 자원 패널의 PDF 뷰어·노트 미리보기를 그대로 재사용한다.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  BookOpen,
  Check,
  CircleAlert,
  CircleCheck,
  CircleX,
  ClipboardCheck,
  FileText,
  FileX,
  Link2,
  LoaderCircle,
  NotebookPen,
  NotebookTabs,
  Plus,
  RotateCcw,
  Save,
} from "lucide-react";
import { api, isMock, setMockQuizScenario } from "./api";
import { ErrorBox, Spinner, WorkspaceNav, shortTime } from "./ui";
import { DocViewer, NotePreview } from "./Workspace";
import "./workspace.css";
import "./study.css";

const MEMO_MAX = 2000;
const answersKey = (quizId) => `studylink-quiz-answers-${quizId}`;
function readAnswers(quizId) {
  try {
    return JSON.parse(localStorage.getItem(answersKey(quizId))) || {};
  } catch {
    return {};
  }
}
function writeAnswers(quizId, value) {
  try {
    if (value) localStorage.setItem(answersKey(quizId), JSON.stringify(value));
    else localStorage.removeItem(answersKey(quizId));
  } catch {
    // 저장 불가여도 화면 상태로 계속 푼다.
  }
}
const isGraded = (quiz) => !!quiz?.submitted_at && quiz.questions?.some((q) => "answer_option_id" in q);
const optionText = (options, optionId) => options?.find((o) => o.option_id === optionId)?.text;
const LETTERS = "ABCDEFGH";

// 워크스페이스 상세(제목·자료·노트)를 불러오고 열람 패널 상태를 관리하는 공통 틀.
function useStudyWorkspace(id) {
  const [workspace, setWorkspace] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [viewer, setViewer] = useState(null);
  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .detail(id)
      .then(setWorkspace)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(load, [load]);
  const refreshNotes = () =>
    api.notes("", id).then((rows) => setWorkspace((w) => ({ ...w, notes: rows })));
  const openEvidence = (item, from) =>
    setViewer({
      kind: "doc",
      document_id: item.document_id,
      filename: item.filename,
      page: Number(item.page) || 1,
      quote: item.quote,
      from,
      nonce: Date.now(),
    });
  const openNote = (noteId, from) => setViewer({ kind: "note", note_id: noteId, from, nonce: Date.now() });
  const openCitation = (c, from) => {
    if (c.source_type === "note") {
      const noteId = c.note_id || c.cited_note_id;
      if (noteId) openNote(noteId, from);
    } else if (c.document_id) openEvidence(c, from);
  };
  return { workspace, loading, error, load, viewer, setViewer, refreshNotes, openEvidence, openNote, openCitation };
}
const docAvailable = (workspace, documentId) =>
  workspace?.documents?.some((d) => d.id === documentId && d.status === "ready");

function StudyFrame({ id, ws, children }) {
  const { workspace, loading, error, load } = ws;
  if (loading) return <Spinner />;
  if (error)
    return (
      <div className="home">
        <Link to="/">← 워크스페이스</Link>
        <ErrorBox message={error} retry={load} />
      </div>
    );
  if (!workspace) return null;
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
      <WorkspaceNav id={id} />
      <div className="study-grid">
        {children}
        <ViewerPanel ws={ws} />
      </div>
    </div>
  );
}

// 오른쪽 열람 패널: 근거 PDF 페이지 또는 노트 미리보기(2일차 컴포넌트 재사용).
function ViewerPanel({ ws }) {
  const { workspace, viewer, setViewer, refreshNotes, openCitation } = ws;
  const ref = useRef(null);
  useEffect(() => {
    if (viewer) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [viewer?.nonce]);
  return (
    <aside className="resources panel study-viewer" aria-label="근거 열람" ref={ref}>
      <div className="panel-heading">
        <h2>
          <BookOpen size={18} />
          근거 열람
        </h2>
        <span className="scope-badge">워크스페이스 공통</span>
      </div>
      {viewer ? (
        <div className="viewer">
          {viewer.kind === "doc" ? (
            <DocViewer
              viewer={viewer}
              doc={workspace.documents?.find((d) => d.id === viewer.document_id)}
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
      ) : (
        <p className="subtle-empty viewer-empty">
          <FileText size={22} />
          근거 페이지나 노트를 누르면
          <br />
          여기에서 원문을 열어요.
        </p>
      )}
    </aside>
  );
}

function EvidenceChip({ item, workspace, onOpen, selected }) {
  const ok = docAvailable(workspace, item.document_id);
  if (!ok)
    return (
      <span className="evidence-chip unavailable" title="자료가 삭제됐거나 처리 실패 상태예요">
        <FileX size={12} />
        {item.filename || "자료"} · {item.page}페이지 · 원문을 열 수 없음
      </span>
    );
  return (
    <button className={`evidence-chip ${selected ? "selected" : ""}`} onClick={onOpen}>
      <FileText size={12} />
      {item.filename || "자료"} · {item.page}페이지
    </button>
  );
}

// ---------------------------------------------------------------------------
// 퀴즈: /w/:id/quiz (목록·새 퀴즈) 와 /w/:id/quiz/:quizId (풀이·채점)
// ---------------------------------------------------------------------------
export function QuizPage() {
  const { id, quizId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const ws = useStudyWorkspace(id);
  const [list, setList] = useState([]),
    [listLoading, setListLoading] = useState(true),
    [listError, setListError] = useState(""),
    [generating, setGenerating] = useState(false),
    [elapsed, setElapsed] = useState(0),
    [genError, setGenError] = useState(""),
    [scenario, setScenario] = useState("normal");
  const loadList = useCallback(() => {
    setListLoading(true);
    setListError("");
    api
      .quizzes(id)
      .then(setList)
      .catch((e) => setListError(e.message))
      .finally(() => setListLoading(false));
  }, [id]);
  useEffect(loadList, [loadList]);
  useEffect(() => {
    if (!generating) return;
    setElapsed(0);
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [generating]);

  async function create() {
    if (generating) return;
    setGenerating(true);
    setGenError("");
    if (isMock) setMockQuizScenario(scenario);
    try {
      const quiz = await api.createQuiz(id, 5);
      loadList();
      navigate(`/w/${id}/quiz/${quiz.quiz_id}`, { state: { created: quiz } });
    } catch (e) {
      setGenError(e.message);
    } finally {
      setGenerating(false);
    }
  }
  const readyDocs = ws.workspace?.documents?.filter((d) => d.status === "ready").length || 0;
  const created =
    quizId && location.state?.created?.quiz_id === quizId ? location.state.created : null;

  return (
    <StudyFrame id={id} ws={ws}>
      <aside className="panel quiz-list" aria-label="최근 퀴즈">
        <div className="panel-heading">
          <h2>
            <ClipboardCheck size={18} />
            퀴즈
          </h2>
          <span className="count">{list.length}</span>
        </div>
        <div className="chat-list-body">
          <button
            className="primary new-quiz"
            onClick={create}
            disabled={generating || !readyDocs}
            title={readyDocs ? "처리 완료 자료에서 5문항을 만들어요" : "처리 완료된 자료가 있어야 퀴즈를 만들 수 있어요"}
          >
            {generating ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}
            {generating ? "문항 만드는 중…" : "새 퀴즈 만들기"}
          </button>
          {isMock && (
            <label className="mock-scenario">
              목 시나리오
              <select value={scenario} onChange={(e) => setScenario(e.target.value)} disabled={generating}>
                <option value="normal">정상 5문항</option>
                <option value="partial">부분 생성(3문항)</option>
                <option value="zero">0문항(422)</option>
                <option value="unavailable">공급자 장애(503)</option>
                <option value="missing_doc">근거 자료 없음 1문항</option>
              </select>
            </label>
          )}
          {generating && (
            <div className="generating" role="status">
              <LoaderCircle size={14} className="spin" />
              <span>
                자료에서 문항을 만들고 검증하는 중… {elapsed}초
                <small>보통 30초 안팎, 길어도 45초 정도 걸려요.</small>
              </span>
            </div>
          )}
          <ErrorBox message={genError} />
          {!readyDocs && (
            <p className="subtle-empty">
              처리 완료된 자료가 없어요.
              <br />
              <Link to={`/w/${id}`}>채팅 화면에서 PDF를 먼저 올려 주세요.</Link>
            </p>
          )}
          <ErrorBox message={listError} retry={loadList} />
          {listLoading && !list.length ? (
            <Spinner />
          ) : (
            list.map((q) => (
              <Link
                key={q.quiz_id}
                to={`/w/${id}/quiz/${q.quiz_id}`}
                className={`chat-item quiz-item ${q.quiz_id === quizId ? "active" : ""}`}
                aria-current={q.quiz_id === quizId ? "page" : undefined}
              >
                <strong>
                  {q.submitted_at ? `${q.score ?? "-"} / ${q.actual_count}점` : `풀이 중 · ${q.actual_count}문항`}
                </strong>
                <small>
                  {shortTime(q.created_at)}
                  {q.actual_count < q.requested_count ? ` · ${q.requested_count}문항 중 ${q.actual_count}문항` : ""}
                </small>
              </Link>
            ))
          )}
          {!listLoading && !list.length && !listError && readyDocs > 0 && (
            <p className="subtle-empty">아직 만든 퀴즈가 없어요.</p>
          )}
        </div>
      </aside>
      <section className="panel quiz-main">
        {quizId ? (
          <QuizRunner
            key={quizId}
            quizId={quizId}
            initial={created}
            ws={ws}
            workspaceId={id}
            onSubmitted={loadList}
          />
        ) : (
          <div className="question-empty">
            <span className="sparkle-tile">
              <ClipboardCheck size={29} />
            </span>
            <h2>워크스페이스 자료로 이해도를 점검해 보세요</h2>
            <p>
              처리 완료된 자료의 서로 다른 페이지에서 4지선다 5문항을 만들어요.
              <br />
              어느 채팅에서 들어와도 같은 퀴즈 목록과 오답노트를 봐요.
            </p>
            <button className="primary" onClick={create} disabled={generating || !readyDocs}>
              {generating ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}
              {generating ? "문항 만드는 중…" : "새 퀴즈 만들기"}
            </button>
          </div>
        )}
      </section>
    </StudyFrame>
  );
}

function QuizRunner({ quizId, initial, ws, workspaceId, onSubmitted }) {
  const [quiz, setQuiz] = useState(initial),
    [loading, setLoading] = useState(!initial),
    [error, setError] = useState(""),
    [answers, setAnswers] = useState(() => readAnswers(quizId)),
    [stage, setStage] = useState("answering"), // answering | missing | confirm
    [submitting, setSubmitting] = useState(false),
    [submitError, setSubmitError] = useState("");
  const load = () => {
    setLoading(true);
    setError("");
    api
      .quiz(quizId)
      .then(setQuiz)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  // 생성 응답으로 바로 그리되, 항상 GET으로 다시 받아 새로고침·재방문 시 서버 상태(제출 여부)를 따른다.
  // (history state의 생성 응답은 새로고침 뒤에도 남으므로 그것만 믿지 않는다.)
  useEffect(load, [quizId]);

  if (loading && !quiz) return <Spinner>퀴즈를 여는 중…</Spinner>;
  if (error && !quiz) return <ErrorBox message={error} retry={load} />;
  if (!quiz) return null;

  const graded = isGraded(quiz);
  const questions = quiz.questions || [];
  const unanswered = questions.filter((q) => !answers[q.question_id]).map((q) => q.question_id);
  const partial = quiz.requested_count && quiz.actual_count < quiz.requested_count;

  function choose(questionId, optionId) {
    if (graded || submitting) return;
    setAnswers((current) => {
      const next = { ...current, [questionId]: optionId };
      writeAnswers(quizId, next);
      return next;
    });
    if (stage !== "answering") setStage("answering");
  }
  function requestSubmit() {
    setSubmitError("");
    if (unanswered.length) {
      setStage("missing");
      document.getElementById(`q-${unanswered[0]}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    } else setStage("confirm");
  }
  async function submit() {
    if (submitting) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const result = await api.submitQuiz(quizId, answers);
      setQuiz(result);
      writeAnswers(quizId, null);
      onSubmitted?.();
    } catch (e) {
      setSubmitError(e.message);
      setStage("answering");
    } finally {
      setSubmitting(false);
    }
  }
  const wrong = graded ? questions.filter((q) => !q.correct).length : 0;

  return (
    <div className="quiz">
      <div className="panel-heading quiz-head">
        <h2>
          <ClipboardCheck size={18} />
          {graded ? "채점 결과" : "퀴즈 풀이"}
          <small>{shortTime(quiz.created_at || quiz.submitted_at)}</small>
        </h2>
        {!graded && (
          <span className="scope-badge">
            {questions.length - unanswered.length} / {questions.length} 답함
          </span>
        )}
      </div>
      <div className="quiz-body">
        {partial && (
          <div className="note-warning" role="status">
            <CircleAlert size={14} />
            <span>
              <b>{quiz.actual_count}문항만 만들었습니다.</b> 요청한 {quiz.requested_count}문항 중 근거와 형식 검증을
              통과한 문항만 냈어요.
            </span>
          </div>
        )}
        {graded && (
          <div className={`score-card ${wrong ? "" : "perfect"}`}>
            <div>
              <span>점수</span>
              <strong>
                {quiz.score} <small>/ {quiz.total ?? questions.length}</small>
              </strong>
            </div>
            <p>
              {wrong ? (
                <>
                  틀린 {wrong}문항은 오답노트에 담겼어요. 근거 페이지와 관련 노트로 복습해 보세요.
                  <Link className="text-button" to={`/w/${workspaceId}/reviews`}>
                    <NotebookTabs size={13} />
                    오답노트 열기
                  </Link>
                </>
              ) : (
                "모든 문항을 맞혔어요."
              )}
            </p>
            <small className="submitted-at">제출 {new Date(quiz.submitted_at).toLocaleString("ko-KR")} · 제출은 한 번으로 확정돼요</small>
          </div>
        )}
        <ol className="question-list">
          {questions.map((q, i) => (
            <QuestionCard
              key={q.question_id}
              index={i}
              q={q}
              graded={graded}
              selected={graded ? q.selected_option_id : answers[q.question_id]}
              missing={stage === "missing" && unanswered.includes(q.question_id)}
              onChoose={(optionId) => choose(q.question_id, optionId)}
              ws={ws}
            />
          ))}
        </ol>
        {!graded && (
          <div className="submit-bar">
            {stage === "missing" && unanswered.length > 0 && (
              <div className="error" role="alert">
                답하지 않은 문항이 {unanswered.length}개 있어요 (
                {questions
                  .map((q, i) => (unanswered.includes(q.question_id) ? `${i + 1}번` : null))
                  .filter(Boolean)
                  .join(", ")}
                ). 모든 문항에 답해야 제출할 수 있어요.
              </div>
            )}
            {stage === "confirm" ? (
              <div className="confirm-row" role="alertdialog" aria-label="제출 확인">
                <span>제출하면 답을 바꿀 수 없어요. 제출할까요?</span>
                <button className="secondary" onClick={() => setStage("answering")} disabled={submitting}>
                  계속 풀기
                </button>
                <button className="primary" onClick={submit} disabled={submitting}>
                  {submitting ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}
                  {submitting ? "채점 중…" : "제출하기"}
                </button>
              </div>
            ) : (
              <button className="primary" onClick={requestSubmit}>
                <Check size={14} />
                제출하기
              </button>
            )}
            <ErrorBox message={submitError} />
          </div>
        )}
      </div>
    </div>
  );
}

function QuestionCard({ index, q, graded, selected, missing, onChoose, ws }) {
  const from = `quiz:${q.question_id}`;
  return (
    <li id={`q-${q.question_id}`} className={`question-card ${missing ? "missing" : ""}`}>
      <div className="question-top">
        <span className="q-number">{index + 1}</span>
        <div>
          <p className="stem">{q.stem}</p>
          <EvidenceChip
            item={q}
            workspace={ws.workspace}
            selected={ws.viewer?.from === from}
            onOpen={() => ws.openEvidence(q, from)}
          />
        </div>
        {graded ? (
          q.correct ? (
            <span className="verdict correct">
              <CircleCheck size={14} />
              정답
            </span>
          ) : (
            <span className="verdict wrong">
              <CircleX size={14} />
              오답
            </span>
          )
        ) : (
          missing && <span className="verdict missing">미응답</span>
        )}
      </div>
      <div className="options" role={graded ? undefined : "radiogroup"} aria-label={`${index + 1}번 선택지`}>
        {q.options.map((o, i) => {
          const isSelected = selected === o.option_id;
          const isAnswer = graded && q.answer_option_id === o.option_id;
          const cls = graded
            ? `${isAnswer ? "answer" : ""} ${isSelected && !isAnswer ? "picked-wrong" : ""} ${isSelected ? "picked" : ""}`
            : isSelected
              ? "picked"
              : "";
          return (
            <button
              key={o.option_id}
              className={`option ${cls}`}
              role={graded ? undefined : "radio"}
              aria-checked={graded ? undefined : isSelected}
              disabled={graded}
              onClick={() => onChoose(o.option_id)}
            >
              <span className="letter">{LETTERS[i]}</span>
              <span className="option-text">{o.text}</span>
              {graded && (isAnswer || isSelected) && (
                <span className="option-tag">
                  {isAnswer && isSelected ? "내 답 · 정답" : isAnswer ? "정답" : "내 답"}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {graded && (
        <div className="explanation">
          <strong>해설</strong>
          <p>{q.explanation}</p>
          {q.quote && (
            <button className="quote-link" onClick={() => ws.openEvidence(q, from)} disabled={!docAvailable(ws.workspace, q.document_id)}>
              <blockquote className="viewer-quote">{q.quote}</blockquote>
            </button>
          )}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// 오답노트: /w/:id/reviews?status=open|reviewed&review=<id>
// ---------------------------------------------------------------------------
export function ReviewsPage() {
  const { id } = useParams();
  const ws = useStudyWorkspace(id);
  const [params, setParams] = useSearchParams();
  const status = params.get("status") === "reviewed" ? "reviewed" : "open";
  const selectedId = params.get("review");
  const [rows, setRows] = useState([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const load = useCallback(() => {
    setLoading(true);
    setError("");
    api
      .reviews(id, status)
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id, status]);
  useEffect(load, [load]);
  const setParam = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };
  // 상태가 바뀐 오답은 현재 필터 목록에서 빠지지만 열어 둔 상세는 유지한다.
  const onUpdated = (review) =>
    setRows((list) =>
      review.status === status
        ? list.map((r) => (r.review_id === review.review_id ? { ...r, ...review } : r))
        : list.filter((r) => r.review_id !== review.review_id),
    );

  return (
    <StudyFrame id={id} ws={ws}>
      <aside className="panel quiz-list" aria-label="오답 목록">
        <div className="panel-heading">
          <h2>
            <NotebookTabs size={18} />
            오답노트
          </h2>
          <span className="count">{rows.length}</span>
        </div>
        <div className="review-filter" role="tablist" aria-label="복습 상태">
          {[
            ["open", "복습 전"],
            ["reviewed", "복습함"],
          ].map(([value, label]) => (
            <button
              key={value}
              role="tab"
              aria-selected={status === value}
              className={status === value ? "active" : ""}
              onClick={() => setParam({ status: value === "open" ? "" : value })}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="chat-list-body">
          <ErrorBox message={error} retry={load} />
          {loading && !rows.length ? (
            <Spinner />
          ) : (
            rows.map((r) => (
              <button
                key={r.review_id}
                className={`chat-item review-item ${r.review_id === selectedId ? "active" : ""}`}
                aria-current={r.review_id === selectedId ? "true" : undefined}
                onClick={() => setParam({ review: r.review_id })}
              >
                <strong>{r.stem}</strong>
                <small>
                  {r.filename} · {r.page}페이지 · {shortTime(r.created_at)}
                  {r.learner_reason ? " · 메모 있음" : ""}
                </small>
              </button>
            ))
          )}
          {!loading && !rows.length && !error && (
            <p className="subtle-empty">
              {status === "open" ? "복습할 오답이 없어요." : "복습함으로 표시한 오답이 없어요."}
              <br />
              <Link to={`/w/${id}/quiz`}>퀴즈를 풀면 틀린 문항이 여기에 쌓여요.</Link>
            </p>
          )}
        </div>
      </aside>
      <section className="panel quiz-main">
        {selectedId ? (
          <ReviewDetail key={selectedId} reviewId={selectedId} ws={ws} workspaceId={id} onUpdated={onUpdated} />
        ) : (
          <div className="question-empty">
            <span className="sparkle-tile">
              <NotebookTabs size={29} />
            </span>
            <h2>오답을 골라 복습을 시작해 보세요</h2>
            <p>
              오답을 열면 근거 페이지와, 문제·정답과 관련된 내 노트를 함께 보여줘요.
              <br />
              틀린 이유를 메모하고 복습을 마치면 "복습함"으로 표시하세요.
            </p>
          </div>
        )}
      </section>
    </StudyFrame>
  );
}

function ReviewDetail({ reviewId, ws, workspaceId, onUpdated }) {
  const [review, setReview] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [memo, setMemo] = useState(""),
    [saving, setSaving] = useState(null), // "memo" | "status"
    [saved, setSaved] = useState(""),
    [actionError, setActionError] = useState("");
  const load = () => {
    setLoading(true);
    setError("");
    api
      .review(reviewId)
      .then((r) => {
        setReview(r);
        setMemo(r.learner_reason || "");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, [reviewId]);
  async function patch(value, kind) {
    setSaving(kind);
    setSaved("");
    setActionError("");
    try {
      const updated = await api.updateReview(reviewId, value);
      // PATCH 응답에는 related_notes가 없으므로 기존 관련 노트를 유지한다.
      setReview((r) => ({ ...r, ...updated, related_notes: r.related_notes }));
      if (kind === "memo") setMemo(updated.learner_reason ?? value.learner_reason);
      setSaved(kind);
      onUpdated(updated);
    } catch (e) {
      setActionError(e.message);
    } finally {
      setSaving(null);
    }
  }

  if (loading) return <Spinner>오답과 관련 노트를 불러오는 중…</Spinner>;
  if (error) return <ErrorBox message={error} retry={load} />;
  if (!review) return null;
  const from = `review:${review.review_id}`;
  const reviewed = review.status === "reviewed";
  const memoChanged = memo !== (review.learner_reason || "");
  const related = review.related_notes || [];

  return (
    <div className="quiz">
      <div className="panel-heading quiz-head">
        <h2>
          <NotebookTabs size={18} />
          오답 복습
          <small>{shortTime(review.created_at)}</small>
        </h2>
        <span className={`review-status ${reviewed ? "done" : ""}`}>{reviewed ? "복습함" : "복습 전"}</span>
      </div>
      <div className="quiz-body">
        <div className="question-card">
          <div className="question-top">
            <span className="q-number">Q</span>
            <div>
              <p className="stem">{review.stem}</p>
              <EvidenceChip
                item={review}
                workspace={ws.workspace}
                selected={ws.viewer?.from === from}
                onOpen={() => ws.openEvidence(review, from)}
              />
            </div>
            <span className="verdict wrong">
              <CircleX size={14} />
              오답
            </span>
          </div>
          <div className="options">
            {review.options.map((o, i) => {
              const isAnswer = o.option_id === review.answer_option_id;
              const isSelected = o.option_id === review.selected_option_id;
              return (
                <div
                  key={o.option_id}
                  className={`option static ${isAnswer ? "answer" : ""} ${isSelected && !isAnswer ? "picked-wrong" : ""}`}
                >
                  <span className="letter">{LETTERS[i]}</span>
                  <span className="option-text">{o.text}</span>
                  {(isAnswer || isSelected) && <span className="option-tag">{isAnswer ? "정답" : "내 답"}</span>}
                </div>
              );
            })}
          </div>
          <div className="explanation">
            <strong>해설</strong>
            <p>{review.explanation}</p>
            {review.quote && <blockquote className="viewer-quote">{review.quote}</blockquote>}
          </div>
        </div>

        <section className="review-section">
          <h3>
            <NotebookPen size={15} />
            관련 노트 <span>{related.length}</span>
          </h3>
          {related.length ? (
            related.map((n) => (
              <button
                key={n.note_id}
                className={`citation-card ${ws.viewer?.kind === "note" && ws.viewer.note_id === n.note_id ? "selected" : ""}`}
                onClick={() => ws.openNote(n.note_id, from)}
              >
                <span className={`source-badge note`}>내 노트</span>
                <div>
                  <strong>
                    {n.title}
                    <em className={n.linked ? "linked" : "unlinked"}>
                      {n.linked ? (
                        <>
                          <Link2 size={10} /> 이 워크스페이스에 연결됨
                        </>
                      ) : (
                        "연결 안 됨"
                      )}
                    </em>
                  </strong>
                  {n.snippet && <p>{n.snippet}</p>}
                </div>
              </button>
            ))
          ) : review.related_notes_status === "unavailable" ? (
            <div className="related-empty" role="status">
              <strong>관련 노트를 지금 불러올 수 없어요</strong>
              <p>검색 서비스에 일시적으로 연결하지 못했어요. 오답 기록은 그대로 있어요.</p>
              <button className="text-button" onClick={load}>
                <RotateCcw size={13} />
                다시 불러오기
              </button>
            </div>
          ) : (
            <div className="related-empty">
              <strong>관련 노트 없음</strong>
              <p>이 문제의 핵심을 노트로 정리해 두면 다음 복습 때 여기에서 바로 열 수 있어요.</p>
              <Link className="text-button" to={`/w/${workspaceId}`}>
                <NotebookPen size={13} />
                채팅 화면의 연결 노트 탭에서 노트 작성하기
              </Link>
            </div>
          )}
        </section>

        <section className="review-section">
          <h3>
            <NotebookPen size={15} />
            틀린 이유 메모
          </h3>
          <textarea
            aria-label="틀린 이유 메모"
            value={memo}
            onChange={(e) => {
              setMemo(e.target.value);
              setSaved("");
            }}
            maxLength={MEMO_MAX}
            rows={4}
            placeholder="예: 잔차 연결과 정규화를 헷갈렸다. 기울기 흐름 관점으로 다시 보기."
          />
          <div className="memo-actions">
            <small>
              {memo.length.toLocaleString()} / {MEMO_MAX.toLocaleString()}자
              {saved === "memo" && !memoChanged ? " · 저장했어요" : ""}
            </small>
            <button
              className="secondary"
              onClick={() => patch({ learner_reason: memo }, "memo")}
              disabled={!memoChanged || !!saving}
            >
              {saving === "memo" ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />}
              메모 저장
            </button>
          </div>
        </section>
        <ErrorBox message={actionError} />
        <div className="submit-bar">
          <button
            className={reviewed ? "secondary" : "primary"}
            onClick={() => patch({ status: reviewed ? "open" : "reviewed" }, "status")}
            disabled={!!saving}
          >
            {saving === "status" ? (
              <LoaderCircle className="spin" size={14} />
            ) : reviewed ? (
              <RotateCcw size={14} />
            ) : (
              <Check size={14} />
            )}
            {reviewed ? "복습 전으로 되돌리기" : "복습함으로 표시"}
          </button>
          {saved === "status" && (
            <small className="status-saved">
              {reviewed ? "복습함으로 옮겼어요. '복습함' 필터에서 볼 수 있어요." : "복습 전으로 되돌렸어요."}
            </small>
          )}
        </div>
      </div>
    </div>
  );
}
