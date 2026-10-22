import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import {
  ArrowRight,
  BookOpen,
  FileText,
  FolderOpen,
  Layers,
  LoaderCircle,
  Plus,
  Sparkles,
  X,
} from "lucide-react";
import { api, isMock } from "./api";
import { ErrorBox, Spinner } from "./ui";
import { Workspace } from "./Workspace";
import { QuizPage, ReviewsPage } from "./Study";
import "./styles.css";
import "./workspace.css";
import "./study.css";

function App() {
  return (
    <BrowserRouter>
      <div className="shell">
        <aside className="sidebar">
          <Link to="/" className="brand">
            <span className="brand-icon">
              <Layers size={24} />
            </span>
            StudyLink<span className="brand-dot">.</span>
          </Link>
          <div className="sidebar-label">MY STUDY</div>
          <NavLink to="/" className="nav-link">
            <FolderOpen size={19} />
            워크스페이스
          </NavLink>
          <div className="sidebar-bottom">
            <div className="avatar">나</div>
            <div>
              <strong>나의 학습 기록</strong>
              <small>로컬 개인 워크스페이스</small>
            </div>
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <span>자료에서 시작해, 이해로 연결하다.</span>
            <span className="local-badge">
              <i />
              {isMock ? "화면 미리보기 · 목 데이터" : "개인 학습 워크스페이스"}
            </span>
          </header>
          <main>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route
                path="/w/:id"
                element={<Workspace key={location.pathname} />}
              />
              <Route path="/w/:id/quiz/:quizId?" element={<QuizPage />} />
              <Route path="/w/:id/reviews" element={<ReviewsPage />} />
              <Route
                path="*"
                element={
                  <div className="empty">
                    <h2>페이지를 찾을 수 없습니다</h2>
                    <Link to="/">워크스페이스로 돌아가기</Link>
                  </div>
                }
              />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
function Home() {
  const [rows, setRows] = useState([]),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [show, setShow] = useState(false);
  const load = () => {
    setLoading(true);
    setError("");
    api
      .list()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);
  return (
    <div className="home">
      <div className="eyebrow">YOUR LEARNING, CONNECTED</div>
      <div className="page-heading">
        <div>
          <h1>나의 워크스페이스</h1>
          <p>흩어진 자료를 모으고, 근거 있는 답을 찾아보세요.</p>
        </div>
        <button className="primary" onClick={() => setShow(true)}>
          <Plus size={18} />새 워크스페이스
        </button>
      </div>
      <section className="intro">
        <div>
          <span className="intro-label">
            <Sparkles size={15} />
            생각을 잇는 공부
          </span>
          <h2>
            읽고, 질문하고,
            <br />
            근거로 이해하세요.
          </h2>
          <p>
            PDF 속 궁금한 내용을 질문하면
            <br />
            답변과 함께 원문의 페이지를 짚어드려요.
          </p>
        </div>
        <div className="intro-art" aria-hidden="true">
          <div className="art-paper">
            <FileText size={28} />
            <span />
            <span />
            <span />
            <b>PDF 자료</b>
          </div>
          <div className="art-connector">······</div>
          <div className="art-answer">
            <Sparkles size={20} />
            <b>이해의 시작</b>
            <span>답변에 연결된 근거</span>
            <em>자료 · 3페이지 ↗</em>
          </div>
        </div>
      </section>
      <div className="section-heading">
        <h2>
          모든 워크스페이스 <span>{rows.length}</span>
        </h2>
        <span>나만의 학습 라이브러리</span>
      </div>
      <ErrorBox message={error} retry={load} />
      {loading ? (
        <Spinner />
      ) : rows.length ? (
        <div className="workspace-grid">
          {rows.map((row, i) => (
            <Link to={`/w/${row.id}`} className="workspace-card" key={row.id}>
              <span className={`workspace-icon color-${i % 3}`}>
                <BookOpen size={23} />
              </span>
              <h3>{row.title}</h3>
              <p>
                {row.goal || "이 워크스페이스에서 새로운 배움을 시작해 보세요."}
              </p>
              <footer>
                <span>
                  {new Date(row.created_at).toLocaleDateString("ko-KR")} 생성
                </span>
                <ArrowRight size={19} />
              </footer>
            </Link>
          ))}
          <button className="create-card" onClick={() => setShow(true)}>
            <Plus size={25} />
            <strong>새로운 배움 시작하기</strong>
            <span>워크스페이스 만들기</span>
          </button>
        </div>
      ) : (
        !error && (
          <div className="empty">
            <FolderOpen size={32} />
            <h3>첫 워크스페이스를 만들어 보세요</h3>
            <p>과목이나 학습 목표별로 자료를 모아둘 수 있어요.</p>
            <button className="secondary" onClick={() => setShow(true)}>
              <Plus size={16} />
              워크스페이스 만들기
            </button>
          </div>
        )
      )}
      {show && <CreateModal close={() => setShow(false)} />}
    </div>
  );
}
function CreateModal({ close }) {
  const navigate = useNavigate(),
    titleRef = useRef(null);
  const [title, setTitle] = useState(""),
    [goal, setGoal] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    const before = document.activeElement;
    titleRef.current?.focus();
    return () => before?.focus();
  }, []);
  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const row = await api.create({ title: title.trim(), goal: goal.trim() });
      navigate(`/w/${row.id}`);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }
  function keyboard(e) {
    if (e.key === "Escape" && !busy) close();
    if (e.key === "Tab") {
      const items = [
        ...e.currentTarget.querySelectorAll(
          "button:not(:disabled), input, textarea",
        ),
      ];
      const first = items[0],
        last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
  return (
    <div className="modal-backdrop">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-heading"
        className="modal"
        onKeyDown={keyboard}
      >
        <button
          className="icon-button modal-close"
          aria-label="닫기"
          onClick={close}
          disabled={busy}
        >
          <X size={20} />
        </button>
        <span className="workspace-icon">
          <BookOpen size={23} />
        </span>
        <h2 id="create-heading">새로운 배움의 시작</h2>
        <p>학습할 주제와 목표를 정해보세요.</p>
        <form onSubmit={submit}>
          <label htmlFor="title">워크스페이스 이름</label>
          <input
            id="title"
            ref={titleRef}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="예: 자연어처리 기초"
            maxLength={100}
            required
          />
          <label htmlFor="goal">
            학습 목표 <span>선택</span>
          </label>
          <textarea
            id="goal"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="이 자료로 무엇을 이해하고 싶나요?"
            maxLength={1000}
            rows={3}
          />
          <ErrorBox message={error} />
          <button className="primary full" disabled={!title.trim() || busy}>
            {busy ? (
              <>
                <LoaderCircle size={17} className="spin" />
                만드는 중…
              </>
            ) : (
              <>
                워크스페이스 만들기
                <ArrowRight size={17} />
              </>
            )}
          </button>
        </form>
      </section>
    </div>
  );
}
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
