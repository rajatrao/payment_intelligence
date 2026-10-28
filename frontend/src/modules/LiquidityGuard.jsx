import { useEffect, useState } from "react";
import { api } from "../api.js";
import { SparkIcon, Spinner } from "../components/Icons.jsx";

const usd = (v) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v || 0);
const usd0 = (v) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v || 0);
const day = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(0)}%`);

function Stat({ label, value, tone = "" }) {
  return (
    <div className="card px-3 py-1.5">
      <div className="label">{label}</div>
      <div className={`font-mono text-sm font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

function BillQueue({ bills, selectedId, onSelect }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="label">Upcoming auto-debits</span>
        <span className="text-[11px] text-slate-500">{bills.length} bills</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-3 py-1.5 font-semibold">Vendor</th>
              <th className="px-2 py-1.5 font-semibold">Debit</th>
              <th className="px-2 py-1.5 text-right font-semibold">3-cycle avg</th>
              <th className="px-2 py-1.5 text-right font-semibold">Forecast</th>
              <th className="px-2 py-1.5 text-right font-semibold">Change</th>
              <th className="px-3 py-1.5 font-semibold">Lines</th>
            </tr>
          </thead>
          <tbody>
            {bills.map((b) => {
              const selected = b.id === selectedId;
              return (
                <tr
                  key={b.id}
                  onClick={() => onSelect(b.id)}
                  className={`cursor-pointer border-t border-slate-100 ${selected ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}
                >
                  <td className="max-w-[180px] truncate px-3 py-1.5 font-mono">{b.descriptor}</td>
                  <td className="px-2 py-1.5 font-mono">{day(b.debit_date)}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">{usd0(b.avg3)}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">
                    {usd0(b.projected)}
                    {!b.classified && <span className={selected ? "text-slate-400" : "text-slate-400"}>*</span>}
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                      b.classified && b.change_pct > 25 ? (selected ? "text-red-300" : "text-red-600") : ""
                    }`}
                  >
                    {b.classified ? pct(b.change_pct) : "—"}
                  </td>
                  <td className="px-3 py-1.5">
                    {!b.classified ? (
                      <span className="tag tag-slate">not classified</span>
                    ) : b.spike ? (
                      <span className="tag tag-red">{b.variable_lines} variable · spike</span>
                    ) : b.variable_lines ? (
                      <span className="tag tag-amber">{b.variable_lines} variable</span>
                    ) : (
                      <span className="tag tag-green">all fixed</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-100 px-3 py-1.5 text-[10px] text-slate-500">
        * not classified yet: shows only what is billed so far
      </div>
    </div>
  );
}

function LineRow({ line, cls }) {
  const p = cls?.probability;
  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="px-3 py-2">
        <div className="text-slate-800">{line.description}</div>
        <div className="mt-0.5 font-mono text-[10px] text-slate-500">
          last 3: {line.history.map(usd0).join(" · ")}
        </div>
      </td>
      <td className="px-2 py-2 text-right font-mono tabular-nums">{usd0(line.mtd)}</td>
      <td className={`px-2 py-2 text-right font-mono tabular-nums ${line.spike ? "font-semibold text-red-600" : ""}`}>
        {line.variable == null ? "—" : usd0(line.projected)}
        {line.variable != null && <div className="text-[10px] font-normal text-slate-500">{pct(line.change_pct)} vs avg</div>}
      </td>
      <td className="w-40 px-3 py-2">
        {!cls ? (
          <span className="text-slate-300">—</span>
        ) : (
          <div className="space-y-1">
            <span className={`tag ${cls.variable ? "tag-amber" : "tag-slate"} font-mono`}>
              {cls.variable ? "VARIABLE" : "FIXED"}
            </span>
            {p != null && (
              <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
                <div className="h-1.5 flex-1 rounded-full bg-slate-100">
                  <div
                    className={`h-1.5 rounded-full ${cls.variable ? "bg-amber-500" : "bg-slate-400"}`}
                    style={{ width: `${Math.max(2, p * 100)}%` }}
                  />
                </div>
                <span className="w-8 text-right font-mono tabular-nums">{Math.round(p * 100)}%</span>
              </div>
            )}
            <div className={`text-[10px] ${cls.agrees_with_rules ? "text-slate-500" : "text-amber-700"}`}>
              {cls.agrees_with_rules ? "rule agrees" : `rule says ${cls.rule.variable ? "variable" : "fixed"}: ${cls.rule.why}`}
            </div>
          </div>
        )}
      </td>
    </tr>
  );
}

function BillDetail({ bill, cls, busy, onClassify }) {
  return (
    <div className="card">
      <div className="card-header">
        <div className="min-w-0">
          <div className="label">Bill</div>
          <div className="truncate text-sm font-semibold">{bill.vendor}</div>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-semibold tabular-nums">{usd(bill.projected)}</div>
          <div className="font-mono text-[11px] text-slate-500">
            auto-debit {day(bill.debit_date)} · {bill.payment_method}
          </div>
        </div>
      </div>
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-3 py-1.5 font-semibold">Invoice line</th>
            <th className="px-2 py-1.5 text-right font-semibold">So far</th>
            <th className="px-2 py-1.5 text-right font-semibold">Forecast</th>
            <th className="px-3 py-1.5 font-semibold">Variable usage?</th>
          </tr>
        </thead>
        <tbody>
          {bill.lines.map((l) => (
            <LineRow key={l.id} line={l} cls={cls?.lines[l.id]} />
          ))}
        </tbody>
      </table>
      <div className="space-y-2 border-t border-slate-100 p-3">
        {cls && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-500">
            <span>
              {cls.agreements}/{bill.lines.length} lines agree with the rule check
            </span>
            <span className="font-mono">{cls.route ? `${cls.model} via ${cls.route}` : cls.source}</span>
          </div>
        )}
        {(cls?.notes || []).map((n) => (
          <div key={n} className="text-[11px] text-slate-500">{n}</div>
        ))}
        <button className="btn-primary w-full" onClick={onClassify} disabled={!!busy}>
          {busy === bill.id ? <Spinner /> : <SparkIcon />}
          {busy === bill.id ? "Classifying lines…" : cls ? "Re-classify lines" : "Classify lines"}
        </button>
      </div>
    </div>
  );
}

function CashTimeline({ forecast, selectedId }) {
  const { account, timeline, totals } = forecast;
  const top = Math.max(account.balance, ...timeline.map((e) => e.balance_after));
  const width = (v) => `${Math.max(0, Math.min(100, (v / top) * 100))}%`;
  return (
    <div className="card">
      <div className="card-header">
        <span className="label">Cash timeline · {account.name}</span>
        <span className="text-[11px] text-slate-500">buffer {usd0(account.minimum_buffer)}</span>
      </div>
      <table className="w-full text-left text-xs">
        <tbody>
          <tr className="text-slate-500">
            <td className="px-3 py-1.5 font-mono">{day(forecast.analysis_date)}</td>
            <td className="px-2 py-1.5">Opening balance</td>
            <td className="px-2 py-1.5" />
            <td className="px-3 py-1.5 text-right font-mono tabular-nums">{usd0(account.balance)}</td>
          </tr>
          {timeline.map((e, i) => (
            <tr
              key={i}
              className={`border-t border-slate-100 ${e.below_buffer ? "bg-red-50" : ""} ${
                e.bill_id && e.bill_id === selectedId ? "font-semibold" : ""
              }`}
            >
              <td className="px-3 py-1.5 font-mono">{day(e.date)}</td>
              <td className="px-2 py-1.5">
                {e.label}
                {e.estimate && <span className="ml-1 text-[10px] text-slate-400">billed so far</span>}
              </td>
              <td className={`px-2 py-1.5 text-right font-mono tabular-nums ${e.amount > 0 ? "text-emerald-600" : ""}`}>
                {e.amount > 0 ? "+" : ""}
                {usd0(e.amount)}
              </td>
              <td className="w-48 px-3 py-1.5">
                <div className="flex items-center gap-2">
                  <div className="relative h-1.5 flex-1 rounded-full bg-slate-100">
                    <div
                      className={`h-1.5 rounded-full ${e.below_buffer ? "bg-red-500" : "bg-emerald-500"}`}
                      style={{ width: width(e.balance_after) }}
                    />
                    <div className="absolute -top-0.5 h-2.5 w-px bg-slate-500" style={{ left: width(account.minimum_buffer) }} />
                  </div>
                  <span
                    className={`w-20 text-right font-mono tabular-nums ${e.below_buffer ? "text-red-600" : "text-slate-700"}`}
                  >
                    {usd0(e.balance_after)}
                  </span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-slate-100 px-3 py-1.5 text-[10px] text-slate-500">
        Low point {usd0(totals.low_point.balance)} on {day(totals.low_point.date)}. The tick on each bar is the buffer.
      </div>
    </div>
  );
}

export default function LiquidityGuard() {
  const [data, setData] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = () =>
    api
      .liquidityBills()
      .then((d) => {
        setData(d);
        setSelectedId((id) => id || d.forecast.bills[0]?.id);
      })
      .catch((e) => setError(`Could not load bills: ${e.message}`));

  useEffect(() => {
    load();
  }, []);

  const classify = async (id) => {
    setBusy(id);
    setError(null);
    try {
      const r = await api.classifyBill(id);
      setData((d) => ({ forecast: r.forecast, classifications: { ...d.classifications, [id]: r.classification } }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const classifyAll = async () => {
    for (const b of data.forecast.bills) {
      setSelectedId(b.id);
      await classify(b.id);
    }
  };

  const reset = async () => {
    setError(null);
    try {
      await api.resetClassifications();
      await load();
    } catch (e) {
      setError(`Could not reset: ${e.message}`);
    }
  };

  if (!data) return error ? <div className="text-sm text-red-600">{error}</div> : <Spinner />;

  const { forecast, classifications } = data;
  const t = forecast.totals;
  const bill = forecast.bills.find((b) => b.id === selectedId);
  const breach = t.first_breach;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Liquidity Guard</h1>
          <p className="text-xs text-slate-500">
            Spot variable usage-based charges before they auto-debit, forecast the real amount and check the cash buffer.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Stat label="Auto-debits" value={`${forecast.bills.length} · ${usd0(t.debits)}`} />
          <Stat label="Variable exposure" value={usd0(t.variable_exposure)} tone="text-amber-600" />
          <Stat
            label="Above 3-cycle avg"
            value={t.unclassified_bills === forecast.bills.length ? "—" : usd0(t.surprise)}
            tone="text-amber-600"
          />
          <Stat
            label="Cash low point"
            value={`${usd0(t.low_point.balance)} · ${day(t.low_point.date)}`}
            tone={breach ? "text-red-600" : "text-emerald-600"}
          />
        </div>
      </div>

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">{error}</div>}
      {breach ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
          The operating account drops below the {usd0(forecast.account.minimum_buffer)} buffer on {day(breach)}
          {t.unclassified_bills ? " even before usage is forecast" : ""}. Low point {usd0(t.low_point.balance)} on{" "}
          {day(t.low_point.date)}.
        </div>
      ) : t.unclassified_bills ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
          {t.unclassified_bills} of {forecast.bills.length} bills aren't classified yet, so their totals show only what is
          billed so far. Classify them to forecast the full cycle.
        </div>
      ) : (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
          The operating account stays above the {usd0(forecast.account.minimum_buffer)} buffer through every auto-debit.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,6fr)_minmax(0,6fr)]">
        <section className="space-y-4">
          <BillQueue bills={forecast.bills} selectedId={selectedId} onSelect={setSelectedId} />
          <div className="flex gap-2">
            <button className="btn-secondary flex-1" onClick={classifyAll} disabled={!!busy}>
              {busy ? <Spinner /> : <SparkIcon />} Classify all bills
            </button>
            <button className="btn-secondary" onClick={reset} disabled={!!busy || !Object.keys(classifications).length}>
              Reset demo
            </button>
          </div>
          <CashTimeline forecast={forecast} selectedId={selectedId} />
        </section>
        <section className="space-y-4">
          {bill && <BillDetail bill={bill} cls={classifications[bill.id]} busy={busy} onClassify={() => classify(bill.id)} />}
          <div className="card px-4 py-3 text-[11px] text-slate-500">
            Variable lines are forecast at their run rate ({forecast.cycle.days} ÷ {forecast.cycle.days_elapsed} days ×
            billed so far); fixed lines at their billed amount. Forecasts are computed by the engine, not the model.
          </div>
        </section>
      </div>
    </div>
  );
}
