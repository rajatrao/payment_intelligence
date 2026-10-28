import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { SparkIcon, Spinner } from "../components/Icons.jsx";

const usd0 = (v) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v || 0);
const usdK = (v) => `$${(v / 1000).toFixed(0)}k`;
const day = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });

// Chart colours: teal median, amber corridor, slate history, red floor (status colour, always labelled).
const C = { p50: "#0d9488", band: "#f59e0b", history: "#64748b", floor: "#dc2626", grid: "#e2e8f0" };
const HISTORY_SHOWN = 60;
const TAGS = { payroll_day: "payroll", month_start: "month start", month_end: "month end", lull: "lull" };

function Stat({ label, value, tone = "" }) {
  return (
    <div className="card px-3 py-1.5">
      <div className="label">{label}</div>
      <div className={`font-mono text-sm font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

function tagsFor(f, i) {
  return Object.entries(TAGS)
    .filter(([k]) => f.covariates[k][i])
    .map(([, label]) => label);
}

function HorizonChart({ f }) {
  const wrap = useRef(null);
  const [hover, setHover] = useState(null);
  const W = 1000, H = 340, M = { l: 64, r: 16, t: 16, b: 40 };
  const hist = f.history.balance.slice(-HISTORY_SHOWN);
  const histDates = f.history.dates.slice(-HISTORY_SHOWN);
  const n = hist.length + f.dates.length;
  const all = [...hist, ...f.p10, ...f.p90, f.floor];
  const step = [10000, 20000, 25000, 50000, 100000].find((st) => (Math.max(...all) - Math.min(...all)) / st <= 5);
  const lo = Math.floor((Math.min(...all) - step / 4) / step) * step;
  const hi = Math.ceil((Math.max(...all) + step / 4) / step) * step;
  const x = (i) => M.l + (i / (n - 1)) * (W - M.l - M.r);
  const y = (v) => M.t + (1 - (v - lo) / (hi - lo)) * (H - M.t - M.b);
  const fx = (i) => x(hist.length + i); // forecast day i (0-based)
  const ticks = Array.from({ length: Math.round((hi - lo) / step) + 1 }, (_, k) => lo + k * step);
  const last = hist.length - 1;

  // The corridor and median start from today's closing balance so they join the history line.
  const p10 = [hist[last], ...f.p10];
  const p50 = [hist[last], ...f.p50];
  const p90 = [hist[last], ...f.p90];
  const fxi = (i) => x(last + i);
  const line = (vals, at) => vals.map((v, i) => `${i ? "L" : "M"}${at(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const band = `${line(p90, fxi)}${p10
    .map((v, i) => [fxi(i), y(v)])
    .reverse()
    .map(([a, b]) => `L${a.toFixed(1)},${b.toFixed(1)}`)
    .join("")}Z`;
  const breachI = f.breach ? f.breach.day - 1 : null;

  const lullRuns = f.dates.map((d, i) => (f.covariates.lull[i] ? i : null)).filter((i) => i != null);
  const onMove = (e) => {
    const r = wrap.current.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((px - M.l) / (W - M.l - M.r)) * (n - 1));
    if (i < 0 || i >= n) return setHover(null);
    setHover({ i, left: ((x(i) / W) * r.width) | 0 });
  };

  const hi_ = hover?.i;
  const isF = hi_ != null && hi_ >= hist.length;
  const fi = isF ? hi_ - hist.length : null;

  return (
    <div ref={wrap} className="relative" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="30-day cash forecast corridor">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={y(t)} y2={y(t)} stroke={C.grid} strokeWidth="1" />
            <text x={M.l - 8} y={y(t) + 4} textAnchor="end" className="fill-slate-500 text-[11px] font-mono">
              {usdK(t)}
            </text>
          </g>
        ))}
        {lullRuns.length > 0 && (
          <rect
            x={fx(lullRuns[0]) - 6}
            width={Math.min(W - M.r, fx(lullRuns[lullRuns.length - 1]) + 6) - (fx(lullRuns[0]) - 6)}
            y={M.t}
            height={H - M.t - M.b}
            fill="#f1f5f9"
          />
        )}
        {f.dates.map((d, i) =>
          f.covariates.payroll_day[i] ? (
            <g key={d}>
              <line x1={fx(i)} x2={fx(i)} y1={M.t} y2={H - M.b} stroke="#cbd5e1" strokeDasharray="2 3" />
              <text x={fx(i)} y={M.t + 10} textAnchor="middle" className="fill-slate-500 text-[10px]">
                payroll
              </text>
            </g>
          ) : null,
        )}
        <line x1={x(last)} x2={x(last)} y1={M.t} y2={H - M.b} stroke="#94a3b8" strokeWidth="1" />
        <text x={x(last) - 4} y={H - M.b - 6} textAnchor="end" className="fill-slate-500 text-[10px]">
          today
        </text>

        <path d={band} fill={C.band} fillOpacity="0.18" stroke={C.band} strokeOpacity="0.6" strokeWidth="1" />
        <path d={line(hist, x)} fill="none" stroke={C.history} strokeWidth="2" strokeLinejoin="round" />
        <path d={line(p50, fxi)} fill="none" stroke={C.p50} strokeWidth="2.5" strokeLinejoin="round" />

        <line x1={M.l} x2={W - M.r} y1={y(f.floor)} y2={y(f.floor)} stroke={C.floor} strokeWidth="2" />
        <text x={M.l + 6} y={y(f.floor) - 6} className="fill-red-600 text-[11px] font-semibold">
          Corporate Liquidity Floor ({usd0(f.floor)})
        </text>

        {f.executed_sweep && f.dates.includes(f.executed_sweep.date) && (
          <g>
            <line
              x1={fx(f.dates.indexOf(f.executed_sweep.date))}
              x2={fx(f.dates.indexOf(f.executed_sweep.date))}
              y1={M.t}
              y2={H - M.b}
              stroke={C.p50}
              strokeDasharray="4 3"
            />
            <text
              x={fx(f.dates.indexOf(f.executed_sweep.date)) - 4}
              y={M.t + 24}
              textAnchor="end"
              className="fill-teal-700 text-[10px] font-semibold"
            >
              sweep +{usdK(f.executed_sweep.amount)}
            </text>
          </g>
        )}
        {breachI != null && (
          <g>
            <circle cx={fx(breachI)} cy={y(f.p10[breachI])} r="5" fill={C.floor} stroke="white" strokeWidth="2" />
            <text x={fx(breachI)} y={y(f.p10[breachI]) + 18} textAnchor="middle" className="fill-red-600 text-[11px] font-semibold">
              P10 breach · day {f.breach.day}
            </text>
          </g>
        )}

        {[0, 7, 14, 21, 29].map((i) => (
          <text key={i} x={fx(i)} y={H - M.b + 16} textAnchor={i === 29 ? "end" : "middle"} className="fill-slate-500 text-[11px] font-mono">
            {day(f.dates[i])}
          </text>
        ))}
        {[0, 30].map((i) => (
          <text key={`h${i}`} x={x(i)} y={H - M.b + 16} textAnchor="middle" className="fill-slate-400 text-[11px] font-mono">
            {day(histDates[i])}
          </text>
        ))}

        {hover && (
          <g>
            <line x1={x(hi_)} x2={x(hi_)} y1={M.t} y2={H - M.b} stroke="#0f172a" strokeOpacity="0.4" />
            {isF ? (
              [f.p90[fi], f.p50[fi], f.p10[fi]].map((v, k) => (
                <circle key={k} cx={x(hi_)} cy={y(v)} r="4" fill={k === 1 ? C.p50 : C.band} stroke="white" strokeWidth="2" />
              ))
            ) : (
              <circle cx={x(hi_)} cy={y(hist[hi_])} r="4" fill={C.history} stroke="white" strokeWidth="2" />
            )}
          </g>
        )}
      </svg>

      {hover && (
        <div
          className="pointer-events-none absolute top-2 z-10 w-52 rounded-md border border-slate-200 bg-white p-2 text-[11px] shadow-lg"
          style={{ left: Math.min(Math.max(hover.left + 12, 0), (wrap.current?.clientWidth || 600) - 216) }}
        >
          {isF ? (
            <>
              <div className="mb-1 flex justify-between font-semibold text-slate-900">
                <span>{day(f.dates[fi])}</span>
                <span className="text-slate-500">day {fi + 1}</span>
              </div>
              {[
                ["P90 optimistic", f.p90[fi], C.band],
                ["P50 median", f.p50[fi], C.p50],
                ["P10 pessimistic", f.p10[fi], C.band],
              ].map(([k, v, c]) => (
                <div key={k} className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-sm" style={{ background: c }} />
                  <span className="flex-1 text-slate-600">{k}</span>
                  <span className={`font-mono tabular-nums ${v < f.floor ? "text-red-600" : "text-slate-900"}`}>{usd0(v)}</span>
                </div>
              ))}
              {tagsFor(f, fi).length > 0 && <div className="mt-1 text-[10px] text-slate-500">{tagsFor(f, fi).join(" · ")}</div>}
            </>
          ) : (
            <div className="flex justify-between">
              <span className="text-slate-600">{day(histDates[hi_])} closing</span>
              <span className="font-mono tabular-nums text-slate-900">{usd0(hist[hi_])}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function StrategicHorizon() {
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [table, setTable] = useState(false);

  const load = () =>
    api
      .horizonForecast()
      .then(setF)
      .catch((e) => setError(`Could not load the forecast: ${e.message}`));

  useEffect(() => {
    load();
  }, []);

  const run = async (what, call) => {
    setBusy(what);
    setError(null);
    try {
      await call();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };
  const sweep = () => run("sweep", async () => setF(await api.executeSweep()));
  const reset = () =>
    run("reset", async () => {
      await api.resetForecast();
      setF(null);
      await load();
    });

  if (!f)
    return error ? (
      <div className="text-sm text-red-600">{error}</div>
    ) : (
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Spinner /> Forecasting 30 days from 180 days of ledger history…
      </div>
    );

  const low = Math.min(...f.p10);
  const lowI = f.p10.indexOf(low);
  const s = f.recommended_sweep;
  const done = f.executed_sweep;
  const fallback = f.source !== "forecast model";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Strategic Horizon Engine</h1>
          <p className="text-xs text-slate-500">
            {f.account.name}: 30-day probabilistic cash forecast with an 80% safety corridor (P10 to P90) against the
            corporate floor.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Stat label="Today" value={usd0(f.history.balance[f.history.balance.length - 1])} />
          <Stat label="P50 in 30 days" value={usd0(f.p50[f.p50.length - 1])} tone="text-teal-700" />
          <Stat
            label="P10 low point"
            value={`${usd0(low)} · ${day(f.dates[lowI])}`}
            tone={low < f.floor ? "text-red-600" : "text-emerald-600"}
          />
          <Stat label="Floor" value={usd0(f.floor)} />
        </div>
      </div>

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">{error}</div>}

      {fallback && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <span className="font-semibold">Statistical fallback in use, not Timestral.</span>{" "}
          {f.notes.join(" ")}
        </div>
      )}

      {f.breach ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-red-300 bg-red-50 px-4 py-3">
          <div className="text-xs text-red-800">
            <div className="text-sm font-semibold">
              System Alert: 80% Safety Corridor Predicts Floor Breach on Day {f.breach.day} ({day(f.breach.date)}).
            </div>
            <div className="mt-0.5">
              P10 falls to {usd0(f.breach.p10)} against the {usd0(f.floor)} floor (median {usd0(f.breach.p50)}).
              {s &&
                ` Recommended: sweep ${usd0(s.amount)} from ${s.from} on ${day(s.date)}, sized from the P10 forecast to cover the ${usd0(
                  s.covers_shortfall,
                )} shortfall with headroom.`}
            </div>
          </div>
          {s && (
            <button className="btn-primary" onClick={sweep} disabled={!!busy}>
              {busy === "sweep" ? <Spinner /> : <SparkIcon />} Execute AI Recommended Pre-Emptive Sweep
            </button>
          )}
        </div>
      ) : done ? (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-800">
          <span className="font-semibold">
            Pre-emptive sweep scheduled: {usd0(done.amount)} from {done.from} on {day(done.date)}.
          </span>{" "}
          The P10 bound now stays above the floor (low point {usd0(low)} on {day(f.dates[lowI])}). Simulated: no money
          moves.
        </div>
      ) : (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs font-medium text-emerald-800">
          The 80% safety corridor stays above the {usd0(f.floor)} floor for all 30 days.
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <span className="label">30-day horizon · {f.account.name}</span>
          <span className="font-mono text-[11px] text-slate-500">
            {fallback ? f.model : `${f.model} · ${f.route}`}
          </span>
        </div>
        <div className="px-3 pt-3">
          <HorizonChart f={f} />
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 px-3 py-2 text-[11px] text-slate-600">
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-4" style={{ background: C.history }} /> Last {HISTORY_SHOWN} days (ledger)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-4" style={{ background: C.p50 }} /> P50 median
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-4 rounded-sm border" style={{ background: "#fef3c7", borderColor: C.band }} /> P10 to P90
            safety corridor (80%)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-4" style={{ background: C.floor }} /> Corporate floor
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-4 rounded-sm bg-slate-100" /> Lull (known covariate)
          </span>
        </div>
      </div>

      <div className="flex gap-2">
        <button className="btn-secondary flex-1" onClick={() => setTable((t) => !t)}>
          {table ? "Hide daily values" : "Show daily values"}
        </button>
        <button className="btn-secondary" onClick={reset} disabled={!!busy}>
          {busy === "reset" ? <Spinner /> : null} Reset
        </button>
      </div>

      {table && (
        <div className="card overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-3 py-1.5 font-semibold">Day</th>
                <th className="px-2 py-1.5 font-semibold">Date</th>
                <th className="px-2 py-1.5 text-right font-semibold">P10</th>
                <th className="px-2 py-1.5 text-right font-semibold">P50</th>
                <th className="px-2 py-1.5 text-right font-semibold">P90</th>
                <th className="px-3 py-1.5 font-semibold">Calendar</th>
              </tr>
            </thead>
            <tbody className="font-mono tabular-nums">
              {f.dates.map((d, i) => (
                <tr key={d} className={`border-t border-slate-100 ${f.p10[i] < f.floor ? "bg-red-50" : ""}`}>
                  <td className="px-3 py-1">{i + 1}</td>
                  <td className="px-2 py-1">{day(d)}</td>
                  <td className={`px-2 py-1 text-right ${f.p10[i] < f.floor ? "text-red-600" : ""}`}>{usd0(f.p10[i])}</td>
                  <td className="px-2 py-1 text-right">{usd0(f.p50[i])}</td>
                  <td className="px-2 py-1 text-right">{usd0(f.p90[i])}</td>
                  <td className="px-3 py-1 font-sans text-slate-500">{tagsFor(f, i).join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card px-4 py-3 text-[11px] text-slate-500">
        Sent to the engine: {f.history_days} days of end-of-day balances and a calendar of known-future covariates
        (payroll days, month start and end, weekends, lulls) over the history and the {f.horizon_days} days ahead. The
        corridor, breach day and sweep size are read from the returned quantiles; the sweep is simulated.
      </div>
    </div>
  );
}
