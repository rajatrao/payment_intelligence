import { Spinner } from "./Icons.jsx";

const LABELS = {
  generate_letter: "gemma3 letter",
  render_pdf: "ReportLab PDF",
};

const STYLE = {
  pending: "bg-slate-50 text-slate-400 ring-slate-200",
  running: "bg-amber-50 text-amber-700 ring-amber-300",
  done: "bg-emerald-50 text-emerald-700 ring-emerald-300",
  failed: "bg-red-50 text-red-700 ring-red-300",
};

export default function PipelineStages({ stages }) {
  return (
    <ol className="grid grid-cols-2 gap-1.5">
      {Object.entries(LABELS).map(([key, label], i) => {
        const s = stages?.[key] || { state: "pending" };
        const fallback = s.fallback || (s.model || "").includes("fallback");
        return (
          <li key={key} className={`rounded-md px-2.5 py-2 ring-1 ring-inset ${STYLE[s.state]}`}>
            <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide">
              {s.state === "running" ? <Spinner className="h-3 w-3" /> : <span>{i + 1}</span>}
              {label}
            </div>
            <div className="mt-0.5 truncate font-mono text-[10px] opacity-80" title={[s.model || s.method || s.error, s.vectors].filter(Boolean).join(" · ")}>
              {s.error || s.model || s.method || s.state}
              {fallback && " ⚠"}
            </div>
            {s.vectors && <div className="truncate text-[10px] opacity-70">{s.vectors}</div>}
          </li>
        );
      })}
    </ol>
  );
}
