import { ValidationReport } from "../types";

const BADGE: Record<string, string> = {
  passed: "bg-green-100 text-green-800", warning: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-800", info: "bg-slate-100 text-slate-700", manual: "bg-blue-100 text-blue-800",
};
const LABEL: Record<string, string> = {
  passed: "Passed", warning: "Warning", failed: "Failed", info: "Info", manual: "Check by eye",
};

export default function ValidationPanel({ report }: { report: ValidationReport }) {
  const s = report.summary;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        {s.passed} passed · {s.warning} warning(s) · {s.failed} failed · {s.manual} need a visual check
      </p>
      <ul className="space-y-2">
        {report.checks.map((c) => (
          <li key={c.id} className="rounded border border-slate-200 p-2">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium">{c.title}</span>
              <span className={`shrink-0 rounded px-2 py-0.5 text-xs ${BADGE[c.status]}`}>{LABEL[c.status]}</span>
            </div>
            {c.details.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">
                {c.details.slice(0, 8).map((d, i) => <li key={i}>{d}</li>)}
              </ul>
            )}
          </li>
        ))}
      </ul>
      {report.generation_warnings.length > 0 && (
        <div>
          <h4 className="label">Generation notes</h4>
          <ul className="list-disc pl-5 text-xs text-slate-600">
            {report.generation_warnings.map((w, i) => <li key={i}>{w.message}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
