import { useRef, useState } from "react";
import { FileIcon, UploadIcon } from "./Icons.jsx";

const ACCEPT = ["application/pdf", "image/jpeg"];

export default function Dropzone({ file, onFile, disabled }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const [error, setError] = useState(null);

  const take = (f) => {
    if (!f) return;
    const ok = ACCEPT.includes(f.type) || /\.(pdf|jpe?g)$/i.test(f.name);
    if (!ok) return setError("Only PDF or JPEG files are accepted.");
    setError(null);
    onFile(f);
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => !disabled && input.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && !disabled && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!disabled) take(e.dataTransfer.files?.[0]);
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed px-4 py-5 text-center transition ${
          over ? "border-slate-900 bg-slate-50" : "border-slate-300 hover:border-slate-400"
        } ${disabled ? "pointer-events-none opacity-60" : ""}`}
      >
        {file ? (
          <div className="flex items-center gap-3 text-left">
            <FileIcon className="h-8 w-8 shrink-0 text-slate-500" />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-slate-800">{file.name}</div>
              <div className="text-xs text-slate-500">
                {(file.size / 1024).toFixed(1)} KB · {file.type || "unknown"} · click or drop to replace
              </div>
            </div>
          </div>
        ) : (
          <>
            <UploadIcon className="mb-1.5 h-6 w-6 text-slate-400" />
            <div className="text-sm font-medium text-slate-700">Drop invoice, contract or receipt evidence</div>
            <div className="text-xs text-slate-500">PDF or JPEG · matched with EmbeddingGemma 2 · up to 15 MB</div>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept=".pdf,.jpg,.jpeg,application/pdf,image/jpeg"
          className="hidden"
          onChange={(e) => take(e.target.files?.[0])}
        />
      </div>
      {error && <p className="mt-1.5 text-xs font-medium text-red-600">{error}</p>}
    </div>
  );
}
