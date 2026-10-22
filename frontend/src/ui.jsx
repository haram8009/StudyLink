import React from "react";
import { LoaderCircle } from "lucide-react";

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
