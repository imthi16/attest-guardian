import { ALL_STAGES, stageLabel } from "./answer-stages";

/**
 * The labels are what someone stares at while waiting, so every node the graph
 * can emit needs one and an unknown node must not leak an internal name.
 */
describe("stageLabel", () => {
  it("has wording for every stage the graph emits", () => {
    for (const stage of ALL_STAGES) {
      expect(stageLabel(stage)).not.toBe("Working…");
      expect(stageLabel(stage).length).toBeGreaterThan(0);
    }
  });

  it("covers the graph's node names", () => {
    // Mirrors `RagGraph._build`; a node added there without a label here would
    // show a raw identifier to the user.
    expect(ALL_STAGES).toEqual(
      expect.arrayContaining([
        "authorize",
        "analyze",
        "retrieve",
        "generate",
        "verify",
        "decide",
        "compose",
        "abstain",
      ]),
    );
  });

  it("describes evidence work rather than writing", () => {
    // The answer is composed from verified spans at the end, so promising
    // "writing" would describe something that never happens.
    expect(stageLabel("verify")).toContain("citation");
    expect(stageLabel("retrieve")).toContain("documents");
  });

  it("falls back neutrally for an unrecognised stage", () => {
    expect(stageLabel("teleport")).toBe("Working…");
    expect(stageLabel("")).toBe("Working…");
  });
});
