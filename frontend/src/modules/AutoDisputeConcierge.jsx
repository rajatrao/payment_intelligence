import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import Dropzone from "../components/Dropzone.jsx";
import MatchPanel from "../components/MatchPanel.jsx";
import MatchResults from "../components/MatchResults.jsx";
import PipelineStages from "../components/PipelineStages.jsx";
import SampleLibrary from "../components/SampleLibrary.jsx";
import { DownloadIcon, FileIcon, SparkIcon, Spinner } from "../components/Icons.jsx";

const RISK_TAG = { HIGH: "tag-red", MEDIUM: "tag-amber", LOW: "tag-green" };

const money = (amount, currency) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount);

function TransactionQueue({ transactions, selectedId, onSelect, disabled }) {
  return (
    <div className="card">
      <div className="card-header">
        <span className="label">Dispute queue</span>
        <span className="text-[11px] text-slate-500">{transactions.length} eligible</span>
      </div>
      <div className="max-h-56 overflow-y-auto">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-3 py-1.5 font-semibold">Descriptor</th>
              <th className="px-2 py-1.5 font-semibold">Auth</th>
              <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
              <th className="px-2 py-1.5 font-semibold">Code</th>
              <th className="px-3 py-1.5 font-semibold">Risk</th>
            </tr>
          </thead>
          <tbody>
            {transactions.map((t) => (
              <tr
                key={t.id}
                onClick={() => !disabled && onSelect(t.id)}
                className={`cursor-pointer border-t border-slate-100 ${
                  t.id === selectedId ? "bg-slate-900 text-white" : "hover:bg-slate-50"
                }`}
              >
                <td className="max-w-[180px] truncate px-3 py-1.5 font-mono">{t.merchant_descriptor}</td>
                <td className="px-2 py-1.5 font-mono tabular-nums">{t.auth_date.slice(5)}</td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums">{money(t.amount, t.currency)}</td>
                <td className="px-2 py-1.5 font-mono">{t.dispute_reason_code}</td>
                <td className="px-3 py-1.5">
                  <span className={`tag ${RISK_TAG[t.risk_tag]}`}>{t.risk_tag}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Field({ label, children, mono = true }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</dt>
      <dd className={`truncate text-xs text-slate-800 ${mono ? "font-mono" : ""}`} title={String(children ?? "")}>
        {children ?? <span className="text-slate-400">null</span>}
      </dd>
    </div>
  );
}

function TransactionDetail({ txn }) {
  return (
    <div className="card">
      <div className="card-header">
        <div className="min-w-0">
          <div className="label">Original transaction</div>
          <div className="truncate text-sm font-semibold">{txn.merchant_legal_name}</div>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-semibold tabular-nums">{money(txn.amount, txn.currency)}</div>
          <div className="font-mono text-[11px] text-slate-500">
            settled {money(txn.settled_amount_usd, "USD")}
            {txn.fx_rate !== 1 && ` @ ${txn.fx_rate}`}
          </div>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 px-4 py-3 sm:grid-cols-3">
        <Field label="Descriptor">{txn.merchant_descriptor}</Field>
        <Field label="Network / card">{`${txn.card_network} ****${txn.card_last4}`}</Field>
        <Field label="Reason code">{`${txn.dispute_reason_code} · ${txn.dispute_reason}`}</Field>
        <Field label="Auth date">{txn.auth_date}</Field>
        <Field label="Post date">{txn.post_date}</Field>
        <Field label="Auth code">{txn.auth_code}</Field>
        <Field label="ARN">{txn.arn}</Field>
        <Field label="Invoice ref">{txn.invoice_reference}</Field>
        <Field label="MCC">{`${txn.mcc} ${txn.mcc_description}`}</Field>
        <Field label="Cardholder" mono={false}>{txn.cardholder}</Field>
        <Field label="Department" mono={false}>{txn.department}</Field>
        <Field label="Merchant country">{txn.merchant_country}</Field>
      </dl>
      <div className="border-t border-slate-100 px-4 py-2.5">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Cardholder memo</div>
        <p className="text-xs text-slate-700">{txn.memo || <span className="text-slate-400">(empty)</span>}</p>
      </div>
    </div>
  );
}

function LetterPreview({ caseState }) {
  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6">
      <article className="mx-auto max-w-2xl rounded bg-white px-8 py-10 shadow">
        <pre className="whitespace-pre-wrap font-serif text-[13px] leading-relaxed text-slate-800">
          {caseState.letter.text}
        </pre>
      </article>
    </div>
  );
}

export default function AutoDisputeConcierge() {
  const [transactions, setTransactions] = useState([]);
  const [sampleTxnId, setSampleTxnId] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [samples, setSamples] = useState([]);
  const [scores, setScores] = useState(null);
  const [scoring, setScoring] = useState(false);
  const [file, setFile] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [matching, setMatching] = useState(false);
  const [caseState, setCaseState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState("letter");
  const [error, setError] = useState(null);
  const poll = useRef(null);

  useEffect(() => {
    api
      .transactions()
      .then((d) => {
        setTransactions(d.transactions);
        setSampleTxnId(d.sample_transaction_id);
        setSelectedId(d.sample_transaction_id);
      })
      .catch((e) => setError(`Could not load transactions: ${e.message}`));
    api
      .samples()
      .then((d) => setSamples(d.samples))
      .catch((e) => setError(`Could not load samples: ${e.message}`));
    return () => clearInterval(poll.current);
  }, []);

  const txn = transactions.find((t) => t.id === selectedId);
  const building = busy || caseState?.status === "processing";
  const running = building || matching;
  const match = evidence?.matches?.[selectedId];
  const buildable = match && match.verdict !== "WEAK_MATCH";

  // Evidence preview (local object URL) until a package exists.
  const evidenceUrl = useMemo(() => (file && file.type === "application/pdf" ? URL.createObjectURL(file) : null), [file]);
  const imageUrl = useMemo(() => (file && file.type.startsWith("image/") ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => evidenceUrl && URL.revokeObjectURL(evidenceUrl), [evidenceUrl]);
  useEffect(() => () => imageUrl && URL.revokeObjectURL(imageUrl), [imageUrl]);

  const resetCase = () => {
    clearInterval(poll.current);
    setCaseState(null);
    setError(null);
  };

  // Match results cover every transaction, so changing the selection keeps them; only the built package resets.
  const selectTxn = (id) => {
    setSelectedId(id);
    resetCase();
  };

  const chooseFile = (f) => {
    setFile(f);
    setEvidence(null);
    resetCase();
  };

  const loadSample = async (sample) => {
    try {
      setError(null);
      chooseFile(await api.sampleFile(sample));
    } catch (e) {
      setError(e.message);
    }
  };

  // "Use Sample PDF": the EUROSITES invoice plus the transaction it backs.
  const useSample = async () => {
    const sample = samples.find((s) => s.expected_transaction_id === sampleTxnId);
    if (!sample) return;
    setSelectedId(sampleTxnId);
    await loadSample(sample);
  };

  const scoreAll = async () => {
    if (!txn) return;
    setScoring(true);
    setError(null);
    try {
      setScores(await api.sampleScores(txn.id));
    } catch (e) {
      setError(e.message);
    } finally {
      setScoring(false);
    }
  };

  // Step 1: score the file against every disputed transaction.
  const matchFile = async () => {
    if (!file) return;
    resetCase();
    setMatching(true);
    try {
      const ev = await api.matchEvidence(file);
      setEvidence(ev);
      if (ev.matched_transaction_id) setSelectedId(ev.matched_transaction_id);
    } catch (e) {
      setError(e.message);
    } finally {
      setMatching(false);
    }
  };

  // Step 2: letter + package for the selected transaction.
  const build = async () => {
    if (!txn || !evidence || !buildable) return;
    resetCase();
    setBusy(true);
    setView("letter");
    try {
      const created = await api.createDispute(txn.id, evidence.evidence_id);
      setCaseState(created);
      poll.current = setInterval(async () => {
        try {
          const c = await api.dispute(created.case_id);
          setCaseState(c);
          if (c.status !== "processing") {
            clearInterval(poll.current);
            if (c.status === "failed") setError(c.error);
          }
        } catch (e) {
          clearInterval(poll.current);
          setError(e.message);
        }
      }, 700);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const packageReady = caseState?.status === "complete";
  const exposure = transactions.reduce((sum, t) => sum + t.settled_amount_usd, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Auto-Dispute Concierge</h1>
          <p className="text-xs text-slate-500">
            Match local evidence against the dispute queue with embeddings, then build and review a chargeback package.
          </p>
        </div>
        <div className="flex gap-2">
          <div className="card px-3 py-1.5">
            <div className="label">Disputable exposure</div>
            <div className="font-mono text-sm font-semibold tabular-nums">{money(exposure, "USD")}</div>
          </div>
          <div className="card px-3 py-1.5">
            <div className="label">High risk</div>
            <div className="font-mono text-sm font-semibold tabular-nums text-red-600">
              {transactions.filter((t) => t.risk_tag === "HIGH").length}
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">{error}</div>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* Left: evidence, match results, transaction */}
        <section className="space-y-4">
          <div className="card">
            <div className="card-header">
              <span className="label">1 · Evidence</span>
              <span className="text-[11px] text-slate-500">PDF text and JPEG images matched with EmbeddingGemma 2</span>
            </div>
            <div className="space-y-3 p-4">
              <Dropzone file={file} onFile={chooseFile} disabled={running} />
              <div className="flex flex-wrap gap-2">
                <button className="btn-secondary" onClick={useSample} disabled={running || !samples.length}>
                  <FileIcon className="h-4 w-4" /> Use Sample PDF
                </button>
                <button className="btn-primary flex-1" onClick={matchFile} disabled={!file || running}>
                  {matching ? <Spinner /> : <SparkIcon />}
                  {matching ? "Matching against dispute queue…" : evidence ? "Match again" : "Match evidence"}
                </button>
              </div>
            </div>
          </div>

          {evidence && (
            <MatchResults
              evidence={evidence}
              transactions={transactions}
              selectedId={selectedId}
              onSelect={selectTxn}
              disabled={running}
            />
          )}

          {evidence && match && (
            <div className="card">
              <div className="card-header">
                <span className="label">2 · Build evidence package</span>
                <span className="truncate font-mono text-[11px] text-slate-500">{txn?.merchant_descriptor}</span>
              </div>
              <div className="space-y-3 p-4">
                <MatchPanel match={match} />
                <button className="btn-primary w-full" onClick={build} disabled={!buildable || running}>
                  {building ? <Spinner /> : <SparkIcon />}
                  {building ? "Building package…" : "Build evidence package"}
                </button>
                {!buildable && (
                  <p className="text-[11px] text-slate-500">
                    This file doesn't support the selected transaction, so no package can be built for it.
                  </p>
                )}
                {(caseState || busy) && <PipelineStages stages={caseState?.stages} />}
              </div>
            </div>
          )}

          <TransactionQueue transactions={transactions} selectedId={selectedId} onSelect={selectTxn} disabled={running} />
          {txn && <TransactionDetail txn={txn} />}

          <SampleLibrary
            samples={samples}
            transactions={transactions}
            txn={txn}
            loadedName={file?.name}
            scores={scores}
            scoring={scoring}
            onLoad={loadSample}
            onScore={scoreAll}
            disabled={running}
          />
        </section>

        {/* Right: evidence preview, then letter and package review */}
        <section className="lg:sticky lg:top-[108px] lg:self-start">
          <div className="card flex h-[calc(100vh-132px)] min-h-[560px] flex-col">
            <div className="card-header gap-3">
              <div className="min-w-0">
                <div className="label">{packageReady ? "Review before download" : file ? "Evidence preview" : "Preview"}</div>
                <div className="truncate font-mono text-[11px] text-slate-500">
                  {packageReady
                    ? `${caseState.case_id} · letter by ${caseState.letter.model}`
                    : file?.name || "No document loaded"}
                </div>
              </div>
              {packageReady && (
                <div className="flex items-center gap-2">
                  {caseState.letter.fallback && <span className="tag tag-amber">Template letter</span>}
                  <div className="flex rounded-md bg-slate-100 p-0.5 text-xs font-medium">
                    {[
                      ["letter", "Letter"],
                      ["package", "Package PDF"],
                    ].map(([key, label]) => (
                      <button
                        key={key}
                        onClick={() => setView(key)}
                        className={`rounded px-2.5 py-1 ${view === key ? "bg-white shadow-sm" : "text-slate-500"}`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="relative flex-1 overflow-hidden bg-slate-100">
              {packageReady && view === "letter" ? (
                <LetterPreview caseState={caseState} />
              ) : packageReady ? (
                <iframe
                  key={caseState.case_id}
                  title="Legal chargeback package"
                  src={`${api.packageUrl(caseState.package_url)}#view=FitH`}
                  className="h-full w-full"
                />
              ) : evidenceUrl ? (
                <iframe title="Evidence preview" src={`${evidenceUrl}#view=FitH`} className="h-full w-full" />
              ) : imageUrl ? (
                <div className="grid h-full place-items-center overflow-auto p-4">
                  <img src={imageUrl} alt="Evidence" className="max-h-full rounded shadow" />
                </div>
              ) : (
                <div className="grid h-full place-items-center p-8 text-center">
                  <div>
                    <FileIcon className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                    <p className="text-sm text-slate-500">Drop evidence or click “Use Sample PDF” to start.</p>
                  </div>
                </div>
              )}
              {running && (
                <div className="absolute inset-x-0 top-0 flex items-center gap-2 bg-amber-50/95 px-4 py-2 text-xs font-medium text-amber-800">
                  <Spinner className="h-3.5 w-3.5" />
                  {matching ? "Matching evidence with EmbeddingGemma 2…" : "Writing the letter and building the package…"}
                </div>
              )}
            </div>

            <div className="flex gap-2 border-t border-slate-200 p-3">
              {packageReady && (
                <button className="btn-secondary py-3" onClick={resetCase}>
                  Discard
                </button>
              )}
              <a
                href={packageReady ? api.packageUrl(caseState.package_url, true) : undefined}
                aria-disabled={!packageReady}
                className={`btn flex-1 py-3 text-sm font-semibold ${
                  packageReady
                    ? "bg-emerald-600 text-white hover:bg-emerald-700"
                    : "pointer-events-none bg-slate-200 text-slate-400"
                }`}
              >
                <DownloadIcon /> Download Legal Chargeback Package (PDF)
              </a>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
