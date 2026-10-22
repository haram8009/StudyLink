import React from "react";
import { NavLink } from "react-router-dom";
import { ClipboardCheck, LoaderCircle, MessageSquare, NotebookTabs } from "lucide-react";

export function ErrorBox({ message, retry }) {
  return (
    message && (
      <div className="error" role="alert">
        <span>{message}</span>
        {retry && (
          <button className="text-button" onClick={retry}>
            다시 시도
          </button>
        )}
      </div>
    )
  );
}
export function Spinner({ children = "불러오는 중…" }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={18} className="spin" />
      {children}
    </div>
  );
}

// 워크스페이스 상단 진입점: 채팅 / 퀴즈 / 오답노트. 퀴즈·오답은 채팅과 무관한 워크스페이스 단위다.
export function WorkspaceNav({ id }) {
  const cls = ({ isActive }) => `ws-tab ${isActive ? "active" : ""}`;
  return (
    <nav className="ws-tabs" aria-label="워크스페이스 메뉴">
      <NavLink end to={`/w/${id}`} className={cls}>
        <MessageSquare size={15} />
        채팅
      </NavLink>
      <NavLink to={`/w/${id}/quiz`} className={cls}>
        <ClipboardCheck size={15} />
        퀴즈
      </NavLink>
      <NavLink to={`/w/${id}/reviews`} className={cls}>
        <NotebookTabs size={15} />
        오답노트
      </NavLink>
    </nav>
  );
}

export function shortTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("ko-KR", { month: "short", day: "numeric" });
}
