import { useEffect, useRef, useState } from "react";
import { renderAsync } from "docx-preview";

interface Props {
  blob: Blob | null;
  busy?: boolean;
  error?: string | null;
  emptyText?: string;
}

/** Renders the REAL generated DOCX in the browser (docx-preview). Close to Word, but not identical. */
export default function PreviewPane({ blob, busy, error, emptyText }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    if (!blob || !host.current) return;
    let cancelled = false;
    host.current.innerHTML = "";
    renderAsync(blob, host.current, undefined, {
      inWrapper: true, ignoreWidth: false, ignoreHeight: false, breakPages: true,
      renderHeaders: true, renderFooters: true, useBase64URL: true,
    })
      .then(() => { if (!cancelled) setRenderError(null); })
      .catch((e: unknown) => { if (!cancelled) setRenderError(String(e)); });
    return () => { cancelled = true; };
  }, [blob]);

  return (
    <div className="relative h-full min-h-[300px] overflow-auto rounded-lg border border-slate-200 bg-slate-200">
      {busy && <div className="absolute right-3 top-3 z-10 rounded bg-white/90 px-2 py-1 text-xs text-slate-600 shadow">Updating preview…</div>}
      {(error || renderError) && (
        <div className="m-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Preview problem: {error || renderError}
        </div>
      )}
      {!blob && !error && <div className="p-6 text-sm text-slate-500">{emptyText || "Nothing to preview yet."}</div>}
      <div ref={host} />
      <p className="sticky bottom-0 bg-slate-100/90 px-3 py-1 text-[11px] text-slate-500">
        Browser preview of the generated file. Word may paginate slightly differently; download the DOCX for the final check.
      </p>
    </div>
  );
}
