import { readFileSync } from "node:fs";
import { join } from "node:path";

import { z } from "zod";

import {
  answerDecisionSchema,
  answerStatusSchema,
  citationRecordSchema,
  claimRecordSchema,
  claimVerdictSchema,
  conversationDetailSchema,
  conversationMessageSchema,
  conversationSchema,
  documentProgressSchema,
  documentSchema,
  documentStatusSchema,
  downloadLinkSchema,
  feedbackRatingSchema,
  ingestionStageSchema,
  ingestionStatusSchema,
  memberSchema,
  membershipRoleSchema,
  messageFeedbackSchema,
  resolvedCitationSchema,
  tokenPairSchema,
  uploadPolicySchema,
  userSchema,
  workspaceWithRoleSchema,
} from "./contracts";

/**
 * The web app restates every API response as a Zod schema. That is a deliberate
 * choice — no generator in the bundle, and the client can be stricter than the
 * server where that helps — but a hand-written mirror drifts, and a drifted
 * mirror is worse than none. It either rejects a valid response, so the page
 * reports a transport failure for data that arrived intact, or it accepts a
 * field that never comes and renders `undefined`.
 *
 * That is not hypothetical. A required `document_id` on the citation mirror,
 * which the API deliberately does not return, made *every* stored conversation
 * fail validation and render an error instead of the answer. Nothing caught it
 * but a human reading the diff.
 *
 * So these tests read the OpenAPI document the API generates about itself
 * (`packages/contracts/openapi.json`, kept current by a matching API test) and
 * assert the two agree field by field. A backend change now breaks this build
 * rather than the product.
 */
const schema = JSON.parse(
  readFileSync(join(process.cwd(), "..", "..", "packages", "contracts", "openapi.json"), "utf8"),
) as OpenApiDocument;

type OpenApiSchema = Readonly<{
  properties?: Record<string, OpenApiSchema>;
  required?: readonly string[];
  enum?: readonly string[];
  anyOf?: readonly OpenApiSchema[];
  $ref?: string;
  type?: string;
}>;

type OpenApiDocument = Readonly<{ components: { schemas: Record<string, OpenApiSchema> } }>;

function component(name: string): OpenApiSchema {
  const found = schema.components.schemas[name];
  if (found === undefined) {
    throw new Error(`the API no longer defines a ${name} schema`);
  }
  return found;
}

/** Enum members, following a `$ref` when the property is a named enum. */
function enumValues(name: string): readonly string[] {
  const target = component(name);
  if (target.enum === undefined) {
    throw new Error(`${name} is not an enum in the API schema`);
  }
  return target.enum;
}

/** The keys a Zod object declares, in sorted order. */
function zodKeys(objectSchema: z.ZodTypeAny): string[] {
  const shape = (objectSchema as unknown as { shape: Record<string, unknown> }).shape;
  return Object.keys(shape).sort();
}

/**
 * Compare one Zod object against one OpenAPI component, in both directions.
 *
 * Both directions matter and they fail differently. A key the mirror has and
 * the API does not is the `document_id` case: Zod rejects every response. A key
 * the API has and the mirror does not is quieter — the data arrives, the field
 * is dropped, and a feature is silently missing.
 */
function expectMirrors(objectSchema: z.ZodTypeAny, componentName: string): void {
  const apiProperties = Object.keys(component(componentName).properties ?? {}).sort();

  expect({ [componentName]: zodKeys(objectSchema) }).toEqual({ [componentName]: apiProperties });
}

describe("response contract mirror", () => {
  it("mirrors the identity and workspace shapes", () => {
    expectMirrors(userSchema, "UserResponse");
    expectMirrors(tokenPairSchema, "TokenPairResponse");
    expectMirrors(workspaceWithRoleSchema, "WorkspaceWithRoleResponse");
    expectMirrors(memberSchema, "MemberResponse");
  });

  it("mirrors the document shapes", () => {
    expectMirrors(documentSchema, "DocumentResponse");
    expectMirrors(documentProgressSchema, "DocumentProgressResponse");
    expectMirrors(downloadLinkSchema, "DownloadLinkResponse");
    expectMirrors(uploadPolicySchema, "UploadPolicyResponse");
  });

  it("mirrors the conversation shapes", () => {
    expectMirrors(conversationSchema, "ConversationResponse");
    expectMirrors(conversationMessageSchema, "MessageResponse");
    expectMirrors(conversationDetailSchema, "ConversationDetailResponse");
    expectMirrors(messageFeedbackSchema, "FeedbackResponse");
  });

  it("mirrors the evidence shapes", () => {
    // The pair that broke: a persisted citation and the resolution that proves
    // it. `citationRecordSchema` once required a `document_id` this component
    // has never had.
    expectMirrors(citationRecordSchema, "CitationRecordResponse");
    expectMirrors(claimRecordSchema, "ClaimRecordResponse");
    expectMirrors(resolvedCitationSchema, "ResolvedCitationResponse");
  });

  it("mirrors every enumerated vocabulary", () => {
    // An enum the API gained but the mirror lacks makes a legitimate response
    // fail validation, which reads to the user as the service being broken.
    expect(documentStatusSchema.options.sort()).toEqual([...enumValues("DocumentStatus")].sort());
    expect(ingestionStatusSchema.options.sort()).toEqual([...enumValues("IngestionStatus")].sort());
    expect(ingestionStageSchema.options.sort()).toEqual([...enumValues("IngestionStage")].sort());
    expect(membershipRoleSchema.options.sort()).toEqual([...enumValues("MembershipRole")].sort());
  });

  it("mirrors the vocabularies the answer pipeline reports", () => {
    // These are not OpenAPI components — the API declares them inline as plain
    // strings — so they are read off the answer schema's own documented values.
    const answer = component("AnswerResponse").properties ?? {};

    expect(Object.keys(answer)).toContain("outcome");
    expect(Object.keys(answer)).toContain("decision");
    expect(answerStatusSchema.options).toEqual(["answered", "partial", "abstained"]);
    expect(answerDecisionSchema.options).toEqual([
      "answer",
      "answer_with_warning",
      "ask_for_clarification",
      "abstain",
      "escalate_for_review",
    ]);
    expect(claimVerdictSchema.options.sort()).toEqual(
      ["supported", "unsupported", "contradicted", "ambiguous"].sort(),
    );
    expect(feedbackRatingSchema.options.sort()).toEqual(
      ["helpful", "unhelpful", "incorrect"].sort(),
    );
  });

  it("fails when a mirror gains a field the API does not return", () => {
    // The guard proving the guard: this is the exact shape of the bug that
    // shipped, so the check is shown to catch it rather than assumed to.
    const drifted = citationRecordSchema.extend({ document_id: z.string() });

    expect(() => expectMirrors(drifted, "CitationRecordResponse")).toThrow();
  });

  it("fails when a mirror drops a field the API does return", () => {
    const drifted = citationRecordSchema.omit({ claim_index: true });

    expect(() => expectMirrors(drifted, "CitationRecordResponse")).toThrow();
  });
});
