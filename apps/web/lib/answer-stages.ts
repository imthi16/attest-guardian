/**
 * Human wording for the pipeline stages the streaming route reports.
 *
 * These are LangGraph node names, so they arrive as identifiers rather than
 * prose. Every node the graph can emit has a label here; an unrecognised one
 * falls back to a neutral message rather than showing a raw internal name to
 * someone waiting for an answer.
 *
 * The labels describe *evidence work*, not text generation, because that is what
 * is actually happening — the answer is composed from verified spans at the end
 * rather than written progressively.
 */
const STAGE_LABELS: Readonly<Record<string, string>> = {
  authorize: "Checking your access…",
  analyze: "Reading your question…",
  retrieve: "Searching your documents…",
  generate: "Drawing an answer from the evidence…",
  verify: "Checking every statement against its citation…",
  decide: "Deciding whether the evidence is strong enough…",
  compose: "Assembling the answer and its citations…",
  abstain: "Not enough evidence — preparing an explanation…",
  final: "Finishing…",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? "Working…";
}

export const ALL_STAGES: readonly string[] = Object.keys(STAGE_LABELS);
