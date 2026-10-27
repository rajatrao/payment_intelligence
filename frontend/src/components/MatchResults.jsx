const VERDICT_TAG = { STRONG_MATCH: "tag-green", PARTIAL_MATCH: "tag-amber", WEAK_MATCH: "tag-red" };
const BAR = { STRONG_MATCH: "bg-emerald-500", PARTIAL_MATCH: "bg-amber-500", WEAK_MATCH: "bg-red-400" };

const money = (amount, currency) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount);

// Step 1 result: one evidence file scored against every disputed transaction.
export default function MatchResults({ evidence, transactions, selectedId, onSelect, disabled }) {
  const byId = Object.fromEntries(transactions.map((t) => [t.id, t]));
  const matched = evidence.matched_transaction_id && byId[evidence.matched_transaction_id];

  return (
    <div className="card">
      <div className="card-header">
        <div className="min-w-0">
          <div className="label">Match results</div>
          <div className="truncate font-mono text-[11px] text-slate-500">
            {evidence.filename} · {evidence.vectors}
          </div>
        </div>
      </div>
      <div
        className={`border-b px-4 py-2.5 text-xs font-medium ${
          matched ? "border-emerald-100 bg-emerald-50 text-emerald-800" : "border-red-100 bg-red-50 text-red-700"
        }`}
      >
        {matched
          ? `Backs ${matched.merchant_descriptor} (${money(matched.amount, matched.currency)}). Select it and build the package.`
          : "This file doesn't match any disputed transaction, so there is no package to build."}
      </div>
      <ul className="divide-y divide-slate-100">
        {evidence.ranking.map((r) => {
          const t = byId[r.transaction_id];
          if (!t) return null;
          return (
            <li
              key={r.transaction_id}
              onClick={() => !disabled && onSelect(r.transaction_id)}
              className={`flex cursor-pointer items-center gap-3 px-4 py-2 ${
                r.transaction_id === selectedId ? "bg-slate-100" : "hover:bg-slate-50"
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate font-mono text-xs text-slate-800">{t.merchant_descriptor}</div>
                <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                  <div className={`h-1.5 rounded-full ${BAR[r.verdict]}`} style={{ width: `${Math.max(2, r.score * 100)}%` }} />
                </div>
              </div>
              <span className="w-20 text-right font-mono text-[11px] tabular-nums text-slate-500">
                {money(t.amount, t.currency)}
              </span>
              <span className={`tag ${VERDICT_TAG[r.verdict]} w-24 justify-center font-mono`}>
                {Math.round(r.score * 100)}% {r.verdict.split("_")[0]}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
