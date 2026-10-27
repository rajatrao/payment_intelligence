import { api } from "../api.js";
import { DownloadIcon } from "./Icons.jsx";

// Demo documents: some back a transaction, some are decoys. Load one to match it, or use "Find evidence" to
// search them all for a transaction.
export default function SampleLibrary({ samples, transactions, txn, loadedName, onLoad, disabled }) {
  const descriptor = (id) => transactions.find((t) => t.id === id)?.merchant_descriptor;

  return (
    <div className="card">
      <div className="card-header">
        <span className="label">Sample evidence library</span>
        <span className="text-[11px] text-slate-500">{samples.length} documents</span>
      </div>
      <ul className="divide-y divide-slate-100">
        {samples.map((s) => {
          const expectedHere = txn && s.expected_transaction_id === txn.id;
          return (
            <li key={s.id} className={`flex items-center gap-3 px-4 py-2 ${loadedName === s.filename ? "bg-slate-50" : ""}`}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-xs font-semibold text-slate-800">{s.title}</span>
                  <span className={`tag ${s.doc_type === "Decoy" ? "tag-amber" : "tag-slate"}`}>{s.doc_type}</span>
                  {s.kind === "jpeg" && <span className="tag tag-slate">JPEG</span>}
                  {expectedHere && <span className="tag tag-green">backs this txn</span>}
                </div>
                <div className="truncate text-[11px] text-slate-500">
                  {s.description}
                  {s.expected_transaction_id ? ` · backs ${descriptor(s.expected_transaction_id)}` : " · backs no transaction"}
                </div>
              </div>
              <button className="btn-secondary px-2 py-1 text-xs" onClick={() => onLoad(s)} disabled={disabled}>
                Load
              </button>
              <a href={api.sampleUrl(s.id, true)} className="text-slate-400 hover:text-slate-700" title="Download">
                <DownloadIcon />
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
