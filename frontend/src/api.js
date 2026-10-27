const BASE = import.meta.env.VITE_API_BASE || "";

async function json(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  health: () => fetch(`${BASE}/api/health`).then(json),
  transactions: () => fetch(`${BASE}/api/disputes/transactions`).then(json),
  samples: () => fetch(`${BASE}/api/disputes/samples`).then(json),
  searchEvidence: (transactionId, limit = 5) =>
    fetch(`${BASE}/api/disputes/transactions/${encodeURIComponent(transactionId)}/evidence-search?limit=${limit}`).then(json),
  evidence: (evidenceId) => fetch(`${BASE}/api/disputes/evidence/${evidenceId}`).then(json),
  sampleUrl: (id, download = false) => `${BASE}/api/disputes/samples/${id}${download ? "?download=true" : ""}`,
  async sampleFile(sample) {
    const res = await fetch(`${BASE}/api/disputes/samples/${sample.id}`);
    if (!res.ok) throw new Error(`Could not load sample ${sample.title}`);
    const blob = await res.blob();
    const type = sample.kind === "jpeg" ? "image/jpeg" : "application/pdf";
    return new File([blob], sample.filename, { type });
  },
  // Step 1: embed the file (or reuse its Chroma vectors) and score it against every disputed transaction.
  matchEvidence(file) {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/api/disputes/evidence`, { method: "POST", body: form }).then(json);
  },
  // Step 2: write the letter and render the package for matched evidence.
  createDispute(transactionId, evidenceId) {
    const form = new FormData();
    form.append("transaction_id", transactionId);
    form.append("evidence_id", evidenceId);
    return fetch(`${BASE}/api/disputes/cases`, { method: "POST", body: form }).then(json);
  },
  dispute: (caseId) => fetch(`${BASE}/api/disputes/cases/${caseId}`).then(json),
  packageUrl: (path, download = false) => `${BASE}${path}${download ? "?download=true" : ""}`,
};
