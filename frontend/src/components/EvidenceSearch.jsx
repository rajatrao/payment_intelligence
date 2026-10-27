import { Spinner } from "./Icons.jsx";

const VERDICT_TAG = { STRONG_MATCH: "tag-green", PARTIAL_MATCH: "tag-amber", WEAK_MATCH: "tag-red" };

const money = (amount, currency) =>
  amount == null ? "—" : `${currency || ""} ${Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2 })}`.trim();

// Reverse search: transaction -> stored files. Chroma shortlists by embedding similarity, then each candidate is
// read by the language model and fully matched. The sample library stands in for a document store such as Drive.
export default function EvidenceSearch({ txn, search, searching, onSearch, onUse, disabled }) {
  const current = search?.transaction_id === txn?.id ? search : null;
  return (
    <div className="card">
      <div className="card-header">
        <div className="min-w-0">
          <div className="label">Find evidence for this transaction</div>
          <div className="truncate text-[11px] text-slate-500">
            {current
              ? `${current.candidates} of ${current.searched_documents} stored files shortlisted by Chroma, top ${current.results.length} verified`
              : "Searches every stored file in Chroma, then verifies the shortlist"}
          </div>
        </div>
        <button className="btn-secondary px-2 py-1 text-xs" onClick={onSearch} disabled={!txn || disabled || searching}>
          {searching && <Spinner className="h-3 w-3" />}
          Search
        </button>
      </div>
      {current && (
        <ul className="divide-y divide-slate-100">
          {current.results.map((r) => (
            <li key={r.doc_id} className="flex items-center gap-3 px-4 py-2">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-xs font-semibold text-slate-800">{r.filename}</span>
                  {r.kind === "jpeg" && <span className="tag tag-slate">JPEG</span>}
                </div>
                <div className="truncate font-mono text-[10px] text-slate-500">
                  {r.extracted
                    ? `${r.extracted.merchant || "?"} · ${money(r.extracted.total_amount, r.extracted.currency)} · ${r.extracted.document_date || "no date"}`
                    : "not read yet"}
                  {` · distance ${r.distance}`}
                </div>
              </div>
              <span className={`tag ${VERDICT_TAG[r.verdict]} font-mono`}>{Math.round(r.score * 100)}%</span>
              <button
                className="btn-secondary px-2 py-1 text-xs"
                onClick={() => onUse(r)}
                disabled={disabled || (!r.sample_id && !r.evidence_available)}
              >
                Use
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
