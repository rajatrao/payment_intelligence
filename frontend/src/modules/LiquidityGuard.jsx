import { useEffect, useState } from "react";
import { api } from "../api.js";
import Donut, { SERIES } from "../components/Donut.jsx";
import { SparkIcon, Spinner } from "../components/Icons.jsx";
import StrategicHorizon from "./StrategicHorizon.jsx";

const usd = (v) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v || 0);
const usd0 = (v) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v || 0);
const day = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const pct = (v) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(0)}%`);
const usdK = (v) => (v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : usd0(v));
const short = (account) => account.name.split(" (")[0].replace(/ account$/, "");

function AccountCard({ account, bills, selected, onSelect }) {
  const own = account.bill_ids.map((id) => bills.find((b) => b.id === id));
  const slices = own.map((b, i) => ({
    id: b.id,
    label: b.vendor,
    value: b.projected,
    color: SERIES[i],
    estimate: !b.classified,
    note: b.classified ? null : "billed so far",
  }));
  const total = account.debits || 1;
  return (
    <button
      onClick={onSelect}
      className={`card w-full p-3 text-left transition ${selected ? "ring-2 ring-slate-900" : "hover:ring-1 hover:ring-slate-300"}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs font-semibold">{account.name}</div>
          <div className="truncate text-[10px] text-slate-500">{account.purpose}</div>
        </div>
        {account.first_breach ? (
          <span className="tag tag-red shrink-0">below buffer {day(account.first_breach)}</span>
        ) : account.unclassified_bills ? (
          <span className="tag tag-slate shrink-0">{account.unclassified_bills} not classified</span>
        ) : (
          <span className="tag tag-green shrink-0">above buffer</span>
        )}
      </div>
      <div className="mt-2 flex items-center gap-3">
        <Donut slices={slices} label="Forecast" />
        <ul className="min-w-0 flex-1 space-y-1 text-[11px]">
          {slices.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5">
              <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: s.color }} />
              <span className="min-w-0 flex-1 truncate text-slate-700">{s.label}</span>
              <span className="font-mono tabular-nums text-slate-900">
                {usdK(s.value)}
                {s.estimate && <span className="text-slate-400">*</span>}
              </span>
              <span className="w-8 text-right font-mono tabular-nums text-slate-500">
                {Math.round((s.value / total) * 100)}%
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 border-t border-slate-100 pt-2 font-mono text-[10px] tabular-nums text-slate-500">
        <div>
          <div className="label">Balance</div>
          <div className="text-slate-800">{usd0(account.balance)}</div>
        </div>
        <div>
          <div className="label">Buffer</div>
          <div className="text-slate-800">{usd0(account.minimum_buffer)}</div>
        </div>
        <div>
          <div className="label">Low point</div>
          <div className={account.first_breach ? "text-red-600" : "text-emerald-600"}>
            {usd0(account.low_point.balance)} · {day(account.low_point.date)}
          </div>
        </div>
      </div>
    </button>
  );
}

function Stat({ label, value, tone = "" }) {
  return (
    <div className="card px-3 py-1.5">
      <div className="label">{label}</div>
      <div className={`font-mono text-sm font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

// Hover breakdown for a bill's Forecast cell: what is billed so far, and how each line is forecast.
function ForecastBreakdown({ bill, cycle, x, y }) {
  const runRate = `× ${cycle.days} ÷ ${cycle.days_elapsed}`;
  return (
    <div
      className="pointer-events-none fixed z-50 w-[480px] rounded-md border border-slate-200 bg-white p-3 text-[11px] text-slate-700 shadow-lg"
      style={{ left: Math.max(8, x - 480), top: y + 8 }}
    >
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="font-semibold text-slate-900">{bill.vendor}</span>
        <span className="text-[10px] text-slate-500">
          {cycle.days_elapsed} of {cycle.days} days billed · debits {day(bill.debit_date)}
        </span>
      </div>
      <table className="w-full">
        <thead className="text-[10px] uppercase tracking-wider text-slate-500">
          <tr>
            <th className="pb-1 text-left font-semibold">Line</th>
            <th className="pb-1 text-right font-semibold">So far</th>
            <th className="pb-1 pl-2 text-left font-semibold">Method</th>
            <th className="pb-1 text-right font-semibold">Forecast</th>
          </tr>
        </thead>
        <tbody className="font-mono tabular-nums">
          {bill.lines.map((l) => (
            <tr key={l.id} className="border-t border-slate-100">
              <td className="max-w-[230px] truncate py-1 pr-2 font-sans">{l.description}</td>
              <td className="py-1 text-right">{usd0(l.mtd)}</td>
              <td className="whitespace-nowrap py-1 pl-2 text-[10px] text-slate-500">
                {l.variable == null ? "not classified" : l.variable ? `variable ${runRate}` : "fixed, as billed"}
              </td>
              <td className={`py-1 text-right ${l.spike ? "text-red-600" : ""}`}>{usd0(l.projected)}</td>
            </tr>
          ))}
          <tr className="border-t border-slate-300 font-semibold text-slate-900">
            <td className="py-1 font-sans">Total</td>
            <td className="py-1 text-right">{usd0(bill.billed_so_far)}</td>
            <td />
            <td className="py-1 text-right">{usd0(bill.projected)}</td>
          </tr>
        </tbody>
      </table>
      <div className="mt-1.5 text-[10px] text-slate-500">
        {bill.classified
          ? `Forecast ${usd0(bill.projected - bill.billed_so_far)} above billed so far; 3-cycle average ${usd0(bill.avg3)} (${pct(
              bill.change_pct,
            )}).`
          : `Not classified yet, so the forecast is what is billed so far. Classify to run-rate the variable lines ${runRate}.`}
      </div>
    </div>
  );
}

function BillQueue({ bills, account, cycle, selectedId, onSelect }) {
  const [hover, setHover] = useState(null);
  const hovered = hover && bills.find((b) => b.id === hover.id);
  return (
    <div className="card">
      {hovered && <ForecastBreakdown bill={hovered} cycle={cycle} x={hover.x} y={hover.y} />}
      <div className="card-header">
        <span className="label">Upcoming auto-debits · {account.name}</span>
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
                  <td className="max-w-[160px] truncate px-3 py-1.5 font-mono">{b.descriptor}</td>
                  <td className="whitespace-nowrap px-2 py-1.5 font-mono">{day(b.debit_date)}</td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">{usd0(b.avg3)}</td>
                  <td
                    className="cursor-help px-2 py-1.5 text-right font-mono tabular-nums underline decoration-dotted decoration-slate-400 underline-offset-2"
                    onMouseEnter={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      setHover({ id: b.id, x: r.right, y: r.bottom });
                    }}
                    onMouseLeave={() => setHover(null)}
                  >
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
                  <td className="whitespace-nowrap px-3 py-1.5">
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
        * not classified yet: shows only what is billed so far. Hover a forecast for its line-by-line breakdown.
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

function CashTimeline({ forecast, account, selectedId }) {
  const { timeline } = account;
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
        Low point {usd0(account.low_point.balance)} on {day(account.low_point.date)}. The tick on each bar is the buffer.
      </div>
    </div>
  );
}

function TacticalLedgerGuard() {
  const [data, setData] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [accountId, setAccountId] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = () =>
    api
      .liquidityBills()
      .then((d) => {
        setData(d);
        setSelectedId((id) => id || d.forecast.bills[0]?.id);
        setAccountId((id) => id || d.forecast.bills[0]?.account_id);
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

  const selectBill = (id) => {
    setSelectedId(id);
    setAccountId(data.forecast.bills.find((b) => b.id === id)?.account_id);
  };

  const selectAccount = (id) => {
    setAccountId(id);
    const first = data.forecast.accounts.find((a) => a.id === id)?.bill_ids[0];
    if (first) setSelectedId(first);
  };

  // Classifies only the bills that debit the selected account.
  const classifyAll = async () => {
    const acct = data.forecast.accounts.find((a) => a.id === accountId) || data.forecast.accounts[0];
    for (const id of acct.bill_ids) {
      selectBill(id);
      await classify(id);
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
  const account = forecast.accounts.find((a) => a.id === accountId) || forecast.accounts[0];
  const accountBills = forecast.bills.filter((b) => b.account_id === account.id);
  const breached = forecast.accounts.filter((a) => a.first_breach).sort((a, b) => (a.first_breach < b.first_breach ? -1 : 1));

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
            label="Accounts below buffer"
            value={`${breached.length} of ${forecast.accounts.length}`}
            tone={breached.length ? "text-red-600" : "text-emerald-600"}
          />
        </div>
      </div>

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">{error}</div>}
      {breached.length ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
          {breached
            .map((a) => `${short(a)} drops below its ${usd0(a.minimum_buffer)} buffer on ${day(a.first_breach)}`)
            .join("; ")}
          .{t.unclassified_bills ? ` ${t.unclassified_bills} bills are still not classified.` : ""}
        </div>
      ) : t.unclassified_bills ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
          {t.unclassified_bills} of {forecast.bills.length} bills aren't classified yet, so their totals show only what is
          billed so far. Classify them to forecast the full cycle.
        </div>
      ) : (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
          Every account stays above its buffer through every auto-debit.
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {forecast.accounts.map((a) => (
          <AccountCard
            key={a.id}
            account={a}
            bills={forecast.bills}
            selected={a.id === account.id}
            onSelect={() => selectAccount(a.id)}
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,6fr)_minmax(0,6fr)]">
        <section className="space-y-4">
          <BillQueue bills={accountBills} account={account} cycle={forecast.cycle} selectedId={selectedId} onSelect={selectBill} />
          <div className="flex gap-2">
            <button className="btn-secondary flex-1" onClick={classifyAll} disabled={!!busy}>
              {busy ? <Spinner /> : <SparkIcon />} Classify all bills · {short(account)}
            </button>
            <button className="btn-secondary" onClick={reset} disabled={!!busy || !Object.keys(classifications).length}>
              Reset
            </button>
          </div>
          <CashTimeline forecast={forecast} account={account} selectedId={selectedId} />
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

const VIEWS = [
  { id: "tactical", label: "Tactical Ledger Guard", hint: "bills, accounts, cash timeline" },
  { id: "strategic", label: "Strategic Horizon Engine", hint: "30-day probabilistic forecast" },
];

export default function LiquidityGuard() {
  const [view, setView] = useState("tactical");
  return (
    <div className="space-y-4">
      <div role="tablist" className="inline-flex rounded-md border border-slate-200 bg-white p-0.5 text-xs font-medium">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            role="tab"
            aria-selected={view === v.id}
            onClick={() => setView(v.id)}
            className={`rounded px-3 py-1.5 transition ${
              view === v.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {v.label}
            <span className={`ml-2 hidden text-[10px] sm:inline ${view === v.id ? "text-slate-300" : "text-slate-400"}`}>
              {v.hint}
            </span>
          </button>
        ))}
      </div>
      {view === "tactical" ? <TacticalLedgerGuard /> : <StrategicHorizon />}
    </div>
  );
}
