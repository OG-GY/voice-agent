import type { Decision } from "@/lib/protocol";

// Shows only the approved fields of the last turn's sanitized trace (rendered as text).
export function DecisionPanel({ decision }: { decision: Decision | null }) {
  return (
    <section className="decision" aria-label="What it decided">
      <h2>What it decided</h2>
      {decision === null ? (
        <p className="muted">Nothing yet.</p>
      ) : (
        <dl>
          <dt>Intent</dt>
          <dd>{decision.intent}</dd>
          <dt>Phase</dt>
          <dd>
            {decision.phaseFrom} → {decision.phaseTo}
          </dd>
          <dt>Actions</dt>
          <dd>{decision.actions.length ? decision.actions.join(", ") : "none"}</dd>
          <dt>Why</dt>
          <dd>{decision.reason}</dd>
        </dl>
      )}
    </section>
  );
}
