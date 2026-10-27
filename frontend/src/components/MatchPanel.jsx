function scoreTone(score) {
  if (score >= 0.7) return { text: "text-emerald-600", tag: "tag-green", bar: "bg-emerald-500" };
  if (score >= 0.45) return { text: "text-amber-600", tag: "tag-amber", bar: "bg-amber-500" };
  return { text: "text-red-600", tag: "tag-red", bar: "bg-red-500" };
}

function cellColor(v, max) {
  const t = max > 0 ? Math.max(0, v) / max : 0;
  return `rgba(15, 23, 42, ${(0.06 + t * 0.85).toFixed(2)})`;
}

export default function MatchPanel({ match }) {
  const tone = scoreTone(match.score);
  const max = Math.max(...match.matrix.flat());

  return (
    <div className="space-y-4">
      {match.note && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
          {match.note}
        </div>
      )}
      <div className="flex items-center gap-4">
        <div className={`font-mono text-4xl font-semibold tabular-nums ${tone.text}`}>
          {Math.round(match.score * 100)}%
        </div>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`tag ${tone.tag}`}>{match.verdict.replace("_", " ")}</span>
            <span className="truncate font-mono text-[11px] text-slate-500">{match.embedding_model}</span>
          </div>
          {[
            [`${match.mode === "image" ? "Visual similarity" : "Semantic (cosine)"} × ${match.semantic_weight}`, match.semantic_score],
            ...(match.field_weight ? [[`Field corroboration × ${match.field_weight}`, match.field_score]] : []),
          ].map(([label, v]) => (
            <div key={label} className="flex items-center gap-2 text-[11px] text-slate-600">
              <span className="w-40 shrink-0">{label}</span>
              <div className="h-1.5 flex-1 rounded bg-slate-100">
                <div className={`h-1.5 rounded ${tone.bar}`} style={{ width: `${v * 100}%` }} />
              </div>
              <span className="w-9 text-right font-mono tabular-nums">{Math.round(v * 100)}%</span>
            </div>
          ))}
        </div>
      </div>

      {match.extracted && (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
          <span className="font-semibold text-slate-700">{match.extracted.model}</span> read this{" "}
          {match.extracted.source === "image" ? "photo" : "PDF"}: {match.extracted.description || "no description"}
          {match.extracted.source !== "image" && " Exact text checks decide for PDFs."}
        </div>
      )}

      <div className="grid grid-cols-2 gap-1.5">
        {match.field_checks.map((c) => (
          <div key={c.field} className="flex items-center justify-between rounded border border-slate-200 px-2 py-1.5">
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-slate-500">{c.field}</div>
              <div className="truncate font-mono text-xs text-slate-800">{c.expected}</div>
              {c.read !== undefined && (
                <div className="truncate font-mono text-[10px] text-slate-400" title="Read from the evidence by the language model">
                  read: {c.read ?? "—"}
                </div>
              )}
            </div>
            {c.applicable === false ? (
              <span className="tag tag-slate">N/A</span>
            ) : (
              <span className={`tag ${c.matched ? "tag-green" : "tag-amber"}`}>{c.matched ? "MATCH" : "MISS"}</span>
            )}
          </div>
        ))}
      </div>

      {match.mode !== "image" && (
        <div>
          <div className="label mb-1.5">Cosine similarity matrix · facets × document chunks</div>
          <div className="overflow-x-auto">
            <table className="border-separate border-spacing-0.5 text-[10px]">
              <tbody>
                {match.matrix.map((row, i) => (
                  <tr key={match.facets[i]}>
                    <th className="pr-2 text-left font-medium capitalize text-slate-500">{match.facets[i]}</th>
                    {row.map((v, j) => (
                      <td
                        key={j}
                        title={`${match.facets[i]} × chunk ${j + 1}: ${v.toFixed(3)}\n${match.chunks[j]}`}
                        className="h-5 w-7 rounded-sm text-center font-mono text-white"
                        style={{ background: cellColor(v, max) }}
                      >
                        {v >= max * 0.75 ? v.toFixed(2).slice(1) : ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
