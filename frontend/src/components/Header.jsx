import { useEffect, useState } from "react";
import { api } from "../api.js";
import { LockIcon } from "./Icons.jsx";

function OllamaBadge() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.health().then((h) => alive && setHealth(h)).catch(() => alive && setHealth({ error: true }));
    load();
    const t = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!health) return <span className="tag tag-slate">Checking Ollama…</span>;
  if (health.error) return <span className="tag tag-red">API offline</span>;

  const o = health.ollama;
  if (!o.reachable) return <span className="tag tag-red" title={o.error}>Ollama unreachable · matching unavailable</span>;
  const ready = o.llm_model && o.embed_model;
  return (
    <span className={`tag ${ready ? "tag-green" : "tag-amber"}`} title={o.base_url}>
      Ollama · {o.llm_model || `${health.config.llm_model} not installed`} ·{" "}
      {o.embed_model || `${health.config.embed_model} not installed`} ·{" "}
      {o.decision_model || `${health.config.decision_model} not installed`}
    </span>
  );
}

export default function Header({ modules, active, onSelect }) {
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 pt-3 sm:px-6">
        <div className="flex items-center gap-3">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-slate-900 text-xs font-bold text-white">PI</div>
          <div>
            <div className="text-sm font-semibold leading-tight">Payment Intelligence</div>
            <div className="text-[11px] text-slate-500">Treasury Optimization Dashboard</div>
          </div>
        </div>
        <OllamaBadge />
      </div>
      <nav className="mx-auto mt-2 flex max-w-[1600px] gap-1 overflow-x-auto px-4 sm:px-6" role="tablist">
        {modules.map((m) => {
          const selected = m.id === active;
          return (
            <button
              key={m.id}
              role="tab"
              aria-selected={selected}
              onClick={() => onSelect(m.id)}
              className={`flex shrink-0 items-center gap-2 rounded-t-md border-b-2 px-3 py-2.5 text-sm font-medium transition ${
                selected
                  ? "border-slate-900 bg-slate-100 text-slate-900"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700"
              }`}
            >
              {m.locked && <LockIcon className="h-3.5 w-3.5 text-slate-400" />}
              {m.label}
            </button>
          );
        })}
      </nav>
    </header>
  );
}
