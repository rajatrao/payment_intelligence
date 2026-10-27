import { useState } from "react";
import Header from "./components/Header.jsx";
import LockWall from "./components/LockWall.jsx";
import AutoDisputeConcierge from "./modules/AutoDisputeConcierge.jsx";
import CardOptimizer from "./modules/CardOptimizer.jsx";

export const MODULES = [
  { id: "disputes", label: "Auto-Dispute Concierge", locked: false },
  { id: "card-optimizer", label: "Card Optimizer", locked: false },
  {
    id: "liquidity-guard",
    label: "Liquidity Guard",
    locked: true,
    lockMessage: "Liquidity Guard pipeline locked until the Card Optimizer review is validated.",
    preview: ["AWS usage", "Google Cloud", "Meta Ads"],
  },
];

export default function App() {
  const [active, setActive] = useState("disputes");
  const module = MODULES.find((m) => m.id === active);

  return (
    <div className="min-h-screen font-sans text-slate-900">
      <Header modules={MODULES} active={active} onSelect={setActive} />
      <main className="mx-auto max-w-[1600px] px-4 py-4 sm:px-6">
        {module.locked ? (
          <LockWall key={module.id} module={module} />
        ) : module.id === "card-optimizer" ? (
          <CardOptimizer />
        ) : (
          <AutoDisputeConcierge />
        )}
      </main>
    </div>
  );
}
