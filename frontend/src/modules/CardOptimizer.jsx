import { useEffect, useState } from "react";
import { api } from "../api.js";
import { SparkIcon, Spinner } from "../components/Icons.jsx";

const usd = (v) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v || 0);
const local = (amount, currency) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: currency === "JPY" ? 0 : 2 }).format(amount);

const STATUS_TAG = { DECLINED: "tag-red", PENDING_AUTH: "tag-amber", SETTLED: "tag-slate" };
const TONE_TAG = { red: "tag-red", amber: "tag-amber" };
const REASON_TAG = {
  SCA_BYPASS_CORRIDOR: "tag-green",
  FX_INTERBANK_MATCH: "tag-green",
  "INTER-REGIONAL_ROUTING": "tag-green",
  NO_CHANGE: "tag-slate",
};

function Stat({ label, value, tone = "" }) {
  return (
    <div className="card px-3 py-1.5">
      <div className="label">{label}</div>
      <div className={`font-mono text-sm font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

function PaymentQueue({ payments, recs, selectedId, onSelect }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="label">Cross-border payments</span>
        <span className="text-[11px] text-slate-500">{payments.length} in corridor review</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-3 py-1.5 font-semibold">Merchant</th>
              <th className="px-2 py-1.5 font-semibold">Corridor</th>
              <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
              <th className="px-2 py-1.5 font-semibold">Status</th>
              <th className="px-3 py-1.5 font-semibold">Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p) => {
              const t = p.transaction;
              const rec = recs[t.id];
              const selected = t.id === selectedId;
              return (
                <tr
                  key={t.id}
                  onClick={() => onSelect(t.id)}
                  className={`cursor-pointer border-t border-slate-100 ${selected ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}
                >
                  <td className="max-w-[170px] truncate px-3 py-1.5 font-mono">{t.descriptor}</td>
                  <td className="px-2 py-1.5 font-mono">
                    {p.corridor.issuer_country}→{p.corridor.merchant_country}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums">{local(t.amount, t.currency)}</td>
                  <td className="px-2 py-1.5">
                    <span className={`tag ${STATUS_TAG[t.status]}`}>{t.status.replace("_", " ")}</span>
                  </td>
                  <td className="px-3 py-1.5">
                    {rec ? (
                      <span className={`tag ${REASON_TAG[rec.reason_code] || "tag-slate"} font-mono`}>{rec.reason_code}</span>
                    ) : (
                      <span className={selected ? "text-slate-400" : "text-slate-300"}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CardOptions({ options, recommendedId }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="label">Card options for this payment</span>
        <span className="text-[11px] text-slate-500">fees computed from the portfolio, not by the model</span>
      </div>
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-3 py-1.5 font-semibold">Card</th>
            <th className="px-2 py-1.5 text-right font-semibold">FX</th>
            <th className="px-2 py-1.5 text-right font-semibold">Cross-border</th>
            <th className="px-2 py-1.5 text-right font-semibold">Fees</th>
            <th className="px-3 py-1.5 font-semibold">Can clear it?</th>
          </tr>
        </thead>
        <tbody>
          {options.map((o) => (
            <tr key={o.card_id} className={`border-t border-slate-100 ${o.card_id === recommendedId ? "bg-emerald-50" : ""}`}>
              <td className="px-3 py-1.5">
                <div className="font-medium text-slate-800">{o.name}</div>
                <div className="text-[10px] text-slate-500">
                  {o.issuer_country} · {o.region}
                  {o.current && " · current card"}
                </div>
              </td>
              <td className="px-2 py-1.5 text-right font-mono tabular-nums">{(o.fx_bps / 100).toFixed(2)}%</td>
              <td className="px-2 py-1.5 text-right font-mono tabular-nums">{(o.cross_border_bps / 100).toFixed(2)}%</td>
              <td className="px-2 py-1.5 text-right font-mono tabular-nums">{usd(o.fee_usd)}</td>
              <td className="px-3 py-1.5">
                {o.eligible ? (
                  <span className="tag tag-green">YES</span>
                ) : (
                  <span className="text-[11px] text-slate-500">{o.issues.join("; ")}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Recommendation({ rec }) {
  const noChange = rec.reason_code === "NO_CHANGE";
  return (
    <div className={`card border-l-4 ${noChange ? "border-l-slate-300" : "border-l-emerald-500"}`}>
      <div className="card-header">
        <span className="label">Recommendation</span>
        <span className="font-mono text-[11px] text-slate-500">
          {rec.route ? `${rec.model} via ${rec.route}` : rec.source}
        </span>
      </div>
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`tag ${REASON_TAG[rec.reason_code] || "tag-slate"} font-mono text-xs`}>{rec.reason_code}</span>
          {!noChange && <span className="text-xs font-semibold text-slate-800">{rec.recommended_card}</span>}
          {rec.confidence != null && !Object.keys(rec.probabilities || {}).length && (
            <span className="text-[11px] text-slate-500">confidence {Math.round(rec.confidence * 100)}%</span>
          )}
        </div>
        <p className="text-sm font-medium text-slate-900">{rec.action}</p>
        <p className="text-xs text-slate-600">{rec.rationale}</p>
        {Object.keys(rec.probabilities || {}).length > 0 && (
          <div className="space-y-1">
            <div className="label">Decision probabilities</div>
            {Object.entries(rec.probabilities)
              .sort((a, b) => b[1] - a[1])
              .map(([code, p]) => (
                <div key={code} className="flex items-center gap-2 text-[11px]">
                  <span className="w-44 truncate font-mono text-slate-600">{code}</span>
                  <div className="h-1.5 flex-1 rounded-full bg-slate-100">
                    <div
                      className={`h-1.5 rounded-full ${code === rec.reason_code ? "bg-emerald-500" : "bg-slate-300"}`}
                      style={{ width: `${Math.max(1, p * 100)}%` }}
                    />
                  </div>
                  <span className="w-10 text-right font-mono tabular-nums text-slate-500">{Math.round(p * 100)}%</span>
                </div>
              ))}
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded border border-slate-200 px-3 py-2">
            <div className="label">Fees saved</div>
            <div className="font-mono text-lg font-semibold tabular-nums text-emerald-600">{usd(rec.fees_saved_usd)}</div>
          </div>
          <div className="rounded border border-slate-200 px-3 py-2">
            <div className="label">Payment recovered</div>
            <div className="font-mono text-lg font-semibold tabular-nums text-emerald-600">{usd(rec.recovered_usd)}</div>
          </div>
        </div>
        <div className={`rounded-md px-3 py-2 text-[11px] ${rec.agrees_with_rules ? "bg-slate-50 text-slate-600" : "bg-amber-50 text-amber-800"}`}>
          {rec.agrees_with_rules
            ? `Rule check agrees: ${rec.rule.reason_code}.`
            : `Rule check disagrees: rules suggest ${rec.rule.reason_code}${rec.rule.card_id ? ` on ${rec.rule.card_id}` : ""} (${rec.rule.why}).`}
        </div>
        {rec.warnings.map((w) => (
          <div key={w} className="rounded-md bg-amber-50 px-3 py-2 text-[11px] text-amber-800">{w}</div>
        ))}
        {(rec.notes || []).map((n) => (
          <div key={n} className="text-[11px] text-slate-500">{n}</div>
        ))}
      </div>
    </div>
  );
}

export default function CardOptimizer() {
  const [data, setData] = useState(null);
  const [recs, setRecs] = useState({});
  const [selectedId, setSelectedId] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .cardPayments()
      .then((d) => {
        setData(d);
        setRecs(d.recommendations || {});
        setSelectedId(d.payments[0]?.transaction.id);
      })
      .catch((e) => setError(`Could not load payments: ${e.message}`));
  }, []);

  const analyse = async (id) => {
    setBusy(id);
    setError(null);
    try {
      const rec = await api.recommendRoute(id);
      setRecs((r) => ({ ...r, [id]: rec }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setError(null);
    try {
      await api.resetRecommendations();
      setRecs({});
    } catch (e) {
      setError(`Could not reset: ${e.message}`);
    }
  };

  const analyseAll = async () => {
    for (const p of data.payments) {
      setSelectedId(p.transaction.id);
      await analyse(p.transaction.id);
    }
  };

  if (!data) return error ? <div className="text-sm text-red-600">{error}</div> : <Spinner />;

  const payment = data.payments.find((p) => p.transaction.id === selectedId);
  const rec = recs[selectedId];
  const all = Object.values(recs);
  const failed = data.payments.filter((p) => p.signals.failed);
  const feesPaid = data.payments.filter((p) => !p.signals.failed).reduce((s, p) => s + p.current_fee_usd, 0);
  const t = payment?.transaction;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Card Optimizer</h1>
          <p className="text-xs text-slate-500">
            Find cross-border payments hitting SCA challenges, regional blocks or FX fees, and route them through the card that clears them.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Stat label="Blocked or pending" value={`${failed.length} · ${usd(failed.reduce((s, p) => s + p.transaction.amount_usd, 0))}`} tone="text-red-600" />
          <Stat label="FX + cross-border fees paid" value={usd(feesPaid)} tone="text-amber-600" />
          <Stat label="Recovered" value={usd(all.reduce((s, r) => s + r.recovered_usd, 0))} tone="text-emerald-600" />
          <Stat label="Fees saved" value={usd(all.reduce((s, r) => s + r.fees_saved_usd, 0))} tone="text-emerald-600" />
        </div>
      </div>

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">{error}</div>}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,6fr)_minmax(0,6fr)]">
        <section className="space-y-4">
          <PaymentQueue payments={data.payments} recs={recs} selectedId={selectedId} onSelect={setSelectedId} />
          <div className="flex gap-2">
            <button className="btn-secondary flex-1" onClick={analyseAll} disabled={!!busy}>
              {busy ? <Spinner /> : <SparkIcon />} Analyze all payments
            </button>
            <button className="btn-secondary" onClick={reset} disabled={!!busy || !Object.keys(recs).length}>
              Reset demo
            </button>
          </div>
        </section>

        {payment && (
          <section className="space-y-4">
            <div className="card">
              <div className="card-header">
                <div className="min-w-0">
                  <div className="label">Payment</div>
                  <div className="truncate text-sm font-semibold">{t.merchant}</div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-lg font-semibold tabular-nums">{local(t.amount, t.currency)}</div>
                  <div className="font-mono text-[11px] text-slate-500">≈ {usd(t.amount_usd)}</div>
                </div>
              </div>
              <div className="space-y-2 px-4 py-3 text-xs">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={`tag ${STATUS_TAG[t.status]}`}>{t.status.replace("_", " ")}</span>
                  {payment.tags.map((tag) => (
                    <span key={tag.label} className={`tag ${TONE_TAG[tag.tone]}`}>{tag.label}</span>
                  ))}
                </div>
                <div className="font-mono text-slate-700">
                  {payment.corridor.issuer_country} ({payment.corridor.issuer_region}) → {payment.corridor.merchant_country} (
                  {payment.corridor.merchant_region}) · MCC {t.mcc} · {t.card_id}
                </div>
                {t.decline_text && (
                  <div className="text-slate-600">
                    {t.decline_code && <span className="font-mono font-semibold">{t.decline_code} · </span>}
                    {t.decline_text}
                  </div>
                )}
                {t.memo && <div className="text-slate-500">{t.memo}</div>}
              </div>
              <div className="border-t border-slate-100 p-3">
                <button className="btn-primary w-full" onClick={() => analyse(t.id)} disabled={!!busy}>
                  {busy === t.id ? <Spinner /> : <SparkIcon />}
                  {busy === t.id ? "Evaluating corridor…" : rec ? "Re-evaluate route" : "Recommend route"}
                </button>
              </div>
            </div>

            {rec && <Recommendation rec={rec} />}
            <CardOptions options={payment.options} recommendedId={rec?.reason_code !== "NO_CHANGE" ? rec?.recommended_card_id : null} />
          </section>
        )}
      </div>
    </div>
  );
}
