import React, { useEffect, useRef, useState } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { api } from "./api";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

// 같은 PDF를 페이지마다 다시 내려받지 않도록 문서 로딩을 주소별로 기억한다.
const documents = new Map();
function loadPdf(url) {
  if (!documents.has(url)) {
    const task = pdfjs.getDocument(url).promise;
    task.catch(() => documents.delete(url));
    documents.set(url, task);
  }
  return documents.get(url);
}

// PDF 한 쪽을 패널 너비에 맞춰 그리고, 인용문 위치에 하이라이트 상자를 겹친다.
// 상자 좌표는 서버(PyMuPDF)가 PDF 포인트 단위·왼쪽 위 기준으로 준다.
export function PdfPage({ url, documentId, page, quote, title }) {
  const wrapRef = useRef(null),
    canvasRef = useRef(null);
  const [size, setSize] = useState(null), // { width, height, scale } CSS 픽셀
    [boxes, setBoxes] = useState([]),
    [error, setError] = useState(""),
    [width, setWidth] = useState(0); // 패널 너비가 바뀌면 다시 그린다

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    setWidth(el.clientWidth); // 관찰 콜백은 화면을 그릴 때만 오므로 처음 너비는 바로 읽는다
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!width) return;
    let cancelled = false,
      renderTask = null;
    setError("");
    loadPdf(url)
      .then((pdf) => pdf.getPage(page))
      .then((pdfPage) => {
        if (cancelled) return;
        const base = pdfPage.getViewport({ scale: 1 });
        const scale = width / base.width;
        const viewport = pdfPage.getViewport({ scale });
        const ratio = window.devicePixelRatio || 1;
        const canvas = canvasRef.current;
        canvas.width = Math.floor(viewport.width * ratio);
        canvas.height = Math.floor(viewport.height * ratio);
        setSize({ width: viewport.width, height: viewport.height, scale });
        renderTask = pdfPage.render({
          canvasContext: canvas.getContext("2d"),
          viewport,
          transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
        });
        return renderTask.promise;
      })
      .catch((e) => {
        if (!cancelled && e?.name !== "RenderingCancelledException") setError("PDF를 표시할 수 없습니다.");
      });
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [url, page, width]);

  useEffect(() => {
    let cancelled = false;
    setBoxes([]);
    if (!quote || !documentId) return;
    api
      .highlight(documentId, page, quote)
      .then((out) => !cancelled && setBoxes(out?.rects || []))
      .catch(() => {}); // 위치를 못 찾아도 쪽과 인용문 블록은 그대로 보인다.
    return () => {
      cancelled = true;
    };
  }, [documentId, page, quote]);

  // 하이라이트가 아래쪽에 있으면 보이도록 스크롤한다.
  useEffect(() => {
    if (!size || !boxes.length || !wrapRef.current) return;
    const top = Math.min(...boxes.map((b) => b[1])) * size.scale;
    wrapRef.current.scrollTop = Math.max(0, top - 80);
  }, [size, boxes]);

  return (
    <div className="pdf-page" ref={wrapRef} aria-label={title}>
      {error ? (
        <p className="pdf-page-error" role="status">{error}</p>
      ) : (
        <div className="pdf-page-inner" style={size ? { width: size.width, height: size.height } : undefined}>
          <canvas ref={canvasRef} style={size ? { width: size.width, height: size.height } : undefined} />
          {size &&
            boxes.map(([x0, y0, x1, y1], i) => (
              <span
                key={i}
                className="pdf-highlight"
                data-testid="pdf-highlight"
                style={{
                  left: x0 * size.scale - 2,
                  top: y0 * size.scale - 1,
                  width: (x1 - x0) * size.scale + 4,
                  height: (y1 - y0) * size.scale + 2,
                }}
              />
            ))}
        </div>
      )}
    </div>
  );
}
