import { LockIcon } from "./Icons.jsx";

// Ghosted skeleton of the future module with a lock overlay on top.
export default function LockWall({ module }) {
  return (
    <div className="relative min-h-[70vh] overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div aria-hidden className="pointer-events-none select-none p-6 opacity-60 blur-[3px]">
        <div className="mb-6 grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded-md bg-slate-100" />
          ))}
        </div>
        <div className="space-y-2">
          {Array.from({ length: 9 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 rounded-md border border-slate-100 px-4 py-3">
              <div className="h-3 w-40 rounded bg-slate-200" />
              <div className="h-3 w-24 rounded bg-slate-100" />
              <div className="ml-auto rounded bg-amber-100 px-2 py-1 font-mono text-[11px] text-amber-700">
                {module.preview[i % module.preview.length]}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="absolute inset-0 grid place-items-center bg-slate-50/70 backdrop-blur-[1px]">
        <div className="mx-4 max-w-md rounded-lg border border-slate-200 bg-white p-6 text-center shadow-lg">
          <div className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-full bg-slate-900 text-white">
            <LockIcon className="h-5 w-5" />
          </div>
          <div className="label mb-1">Pipeline locked</div>
          <p className="text-sm font-medium text-slate-800">{module.lockMessage}</p>
          <p className="mt-3 text-xs text-slate-500">
            This module isn't available yet. Its API routes currently return <span className="font-mono">423 Locked</span>.
          </p>
        </div>
      </div>
    </div>
  );
}
