/**
 * Runtime contracts for the FastAPI endpoints this client consumes.
 *
 * Every response crossing the network boundary is parsed before it reaches a
 * component, so an unexpected or malformed payload becomes a stable typed
 * failure instead of an undefined field rendered into the page. The shapes
 * mirror `apps/api/app/schemas/{auth,workspaces,documents}.py`; the API remains
 * the authority on authorization, and these types only describe what it
 * returns.
 */
import { z } from "zod";

export const membershipRoleSchema = z.enum(["owner", "admin", "member", "viewer"]);
export type MembershipRole = z.infer<typeof membershipRoleSchema>;

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
});
export type User = z.infer<typeof userSchema>;

export const tokenPairSchema = z.object({
  access_token: z.string().min(1),
  refresh_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
});
export type TokenPair = z.infer<typeof tokenPairSchema>;

export const workspaceWithRoleSchema = z.object({
  id: z.string(),
  name: z.string(),
  slug: z.string(),
  created_at: z.string(),
  role: membershipRoleSchema,
});
export type WorkspaceWithRole = z.infer<typeof workspaceWithRoleSchema>;

export const workspaceListSchema = z.array(workspaceWithRoleSchema);

export const memberSchema = z.object({
  user_id: z.string(),
  email: z.string(),
  full_name: z.string(),
  role: membershipRoleSchema,
  joined_at: z.string(),
});
export type Member = z.infer<typeof memberSchema>;

export const memberListSchema = z.array(memberSchema);

export const documentStatusSchema = z.enum([
  "pending",
  "processing",
  "ready",
  "failed",
  "quarantined",
]);
export type DocumentStatus = z.infer<typeof documentStatusSchema>;

export const ingestionStatusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
export type IngestionStatus = z.infer<typeof ingestionStatusSchema>;

export const ingestionStageSchema = z.enum([
  "uploaded",
  "validating",
  "scanning",
  "parsing",
  "ocr",
  "normalizing",
  "chunking",
  "embedding",
  "indexing",
  "ready",
]);
export type IngestionStage = z.infer<typeof ingestionStageSchema>;

export const documentSchema = z.object({
  id: z.string(),
  title: z.string(),
  source_filename: z.string(),
  mime_type: z.string(),
  size_bytes: z.number().int().nonnegative(),
  sha256: z.string(),
  status: documentStatusSchema,
  created_at: z.string(),
  archived_at: z.string().nullable(),
  /**
   * Whether *this* caller may ask for another ingestion run, decided by the API
   * from the document's state, the permanence of its last failure, and the
   * caller's role. Controls read this instead of inferring a retry from
   * `status === "failed"`: a deterministic failure — a hash mismatch, an
   * unparseable file — is refused with a 409 however many times it is asked for.
   */
  retryable: z.boolean(),
});
export type Document = z.infer<typeof documentSchema>;

export const documentListSchema = z.array(documentSchema);

/**
 * Lifecycle progress for one document. `retryable` is computed by the API from
 * server state *and the caller's role*, so the UI never has to reimplement when
 * reprocessing is safe and never offers a button the caller would be refused.
 */
export const documentProgressSchema = z.object({
  document_id: z.string(),
  status: documentStatusSchema,
  job_status: ingestionStatusSchema.nullable(),
  stage: ingestionStageSchema.nullable(),
  attempts: z.number().int().nonnegative(),
  error: z.string().nullable(),
  updated_at: z.string(),
  archived: z.boolean(),
  retryable: z.boolean(),
});
export type DocumentProgress = z.infer<typeof documentProgressSchema>;

export const downloadLinkSchema = z.object({
  url: z.string(),
  expires_in_seconds: z.number().int().positive(),
});
export type DownloadLink = z.infer<typeof downloadLinkSchema>;

/**
 * The upload limits the API deployment actually enforces.
 *
 * Fetched rather than mirrored: `max_upload_bytes` is per-environment
 * configuration, so a compiled-in copy of the default would reject files a
 * raised limit allows and advertise files a lowered limit refuses.
 */
export const uploadPolicySchema = z.object({
  max_upload_bytes: z.number().int().positive(),
  max_filename_length: z.number().int().positive(),
  accepted_extensions: z.array(z.string()).nonempty(),
});
export type UploadPolicy = z.infer<typeof uploadPolicySchema>;

export const answerStatusSchema = z.enum(["answered", "partial", "abstained"]);
export type AnswerStatus = z.infer<typeof answerStatusSchema>;

export const claimVerdictSchema = z.enum(["supported", "unsupported", "contradicted", "ambiguous"]);
export type ClaimVerdict = z.infer<typeof claimVerdictSchema>;

/**
 * The calibrated operational decision. Distinct from `answer_status`: three
 * different decisions all surface as `abstained`, and only this says which.
 */
export const answerDecisionSchema = z.enum([
  "answer",
  "answer_with_warning",
  "ask_for_clarification",
  "abstain",
  "escalate_for_review",
]);
export type AnswerDecision = z.infer<typeof answerDecisionSchema>;

export const conversationSchema = z.object({
  id: z.string(),
  title: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Conversation = z.infer<typeof conversationSchema>;

export const conversationListSchema = z.array(conversationSchema);

/**
 * One persisted evidence span. `document_version_id` is what makes a stored
 * citation resolvable, so evidence stays reachable after the response that
 * produced it is gone.
 */
export const citationRecordSchema = z.object({
  chunk_id: z.string(),
  document_id: z.string(),
  document_version_id: z.string(),
  claim_text: z.string(),
  quote_text: z.string(),
  quote_start: z.number().int().nonnegative(),
  quote_end: z.number().int().nonnegative(),
  page_number: z.number().int().nullable(),
});
export type CitationRecord = z.infer<typeof citationRecordSchema>;

export const claimRecordSchema = z.object({
  claim_index: z.number().int().nonnegative(),
  claim_text: z.string(),
  verdict: claimVerdictSchema,
  confidence: z.number(),
  verifier: z.string(),
});
export type ClaimRecord = z.infer<typeof claimRecordSchema>;

/**
 * One turn. `content` is tenant text — a question someone typed or an answer
 * composed from their documents — so it is rendered as a text child only.
 */
export const conversationMessageSchema = z.object({
  id: z.string(),
  role: z.enum(["user", "assistant", "system"]),
  content: z.string(),
  language: z.string().nullable(),
  normalized_content: z.string().nullable(),
  transliterated_content: z.string().nullable(),
  answer_status: answerStatusSchema.nullable(),
  decision: answerDecisionSchema.nullable(),
  decision_reason: z.string().nullable(),
  confidence: z.number().nullable(),
  abstention_reason: z.string().nullable(),
  created_at: z.string(),
  citations: z.array(citationRecordSchema),
  claims: z.array(claimRecordSchema),
});
export type ConversationMessage = z.infer<typeof conversationMessageSchema>;

export const conversationDetailSchema = z.object({
  conversation: conversationSchema,
  messages: z.array(conversationMessageSchema),
});
export type ConversationDetail = z.infer<typeof conversationDetailSchema>;

/** A citation proven against stored provenance, for the evidence panel. */
export const resolvedCitationSchema = z.object({
  document_id: z.string(),
  document_title: z.string(),
  document_version_id: z.string(),
  version_number: z.number().int(),
  chunk_id: z.string(),
  chunk_index: z.number().int(),
  page_number: z.number().int().nullable(),
  section: z.string().nullable(),
  language: z.string().nullable(),
  quote: z.string(),
  quote_char_start: z.number().int(),
  quote_char_end: z.number().int(),
  page_quote_char_start: z.number().int(),
  page_quote_char_end: z.number().int(),
  supporting_text: z.string(),
  ocr_engine: z.string().nullable(),
});
export type ResolvedCitation = z.infer<typeof resolvedCitationSchema>;

export const feedbackRatingSchema = z.enum(["helpful", "unhelpful", "incorrect"]);
export type FeedbackRating = z.infer<typeof feedbackRatingSchema>;

export const messageFeedbackSchema = z.object({
  id: z.string(),
  message_id: z.string(),
  rating: feedbackRatingSchema,
  note: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type MessageFeedback = z.infer<typeof messageFeedbackSchema>;

export const messageFeedbackListSchema = z.array(messageFeedbackSchema);

/**
 * The API's stable error envelope: `{"detail": {"code", "message"}}`. Clients
 * branch on `code`; `message` is human wording and may change.
 */
export const apiErrorDetailSchema = z.object({
  detail: z.object({
    code: z.string(),
    message: z.string(),
  }),
});

/** Error codes the UI reacts to specifically. */
export const errorCodes = {
  answerFailed: "answer_failed",
  cannotManageRole: "cannot_manage_role",
  citationNotFound: "citation_not_found",
  citationOutOfRange: "citation_out_of_range",
  conversationNotFound: "conversation_not_found",
  contentMismatch: "content_mismatch",
  documentArchived: "document_archived",
  documentDeleteRequiresArchive: "document_delete_requires_archive",
  documentNotFound: "document_not_found",
  documentNotRetryable: "document_not_retryable",
  duplicateDocument: "duplicate_document",
  emailAlreadyRegistered: "email_already_registered",
  feedbackRequiresAnswer: "feedback_requires_answer",
  emptyFile: "empty_file",
  fileTooLarge: "file_too_large",
  insufficientRole: "insufficient_role",
  invalidCredentials: "invalid_credentials",
  invalidRefreshToken: "invalid_refresh_token",
  lastOwner: "last_owner",
  memberAlreadyExists: "member_already_exists",
  messageNotFound: "message_not_found",
  mimeMismatch: "mime_mismatch",
  notAuthenticated: "not_authenticated",
  rateLimited: "rate_limited",
  slugAlreadyExists: "slug_already_exists",
  unsupportedFileType: "unsupported_file_type",
  userNotFound: "user_not_found",
  workspaceDocumentLimitReached: "workspace_document_limit_reached",
  workspaceNotFound: "workspace_not_found",
  workspaceStorageQuotaExceeded: "workspace_storage_quota_exceeded",
} as const;

/** Local codes for failures that never reach the API. */
export const clientErrorCodes = {
  forbidden: "forbidden",
  invalidResponse: "invalid_api_response",
  network: "api_unreachable",
  uploadAborted: "upload_aborted",
  validation: "invalid_input",
} as const;
