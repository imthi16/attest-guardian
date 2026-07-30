/**
 * One conversation, rendered turn by turn.
 *
 * Every assistant turn shows what the platform decided and why before it shows
 * the answer, so a refusal or a cautious answer can never be mistaken for a
 * confident one. Claims carry their own verdict, and each citation opens the
 * passage it rests on.
 *
 * Question text, answer text, claim text, and quotes all originate in user input
 * or uploaded documents. They are rendered as text children throughout; nothing
 * on this page interpolates them into markup.
 */
import {
  AnswerBadge,
  ConfidenceMeter,
  VerdictBadge,
  describeAnswer,
  explainReason,
} from "./answer-state";
import { AnswerFeedback } from "./answer-feedback";
import { EvidencePanel } from "./evidence-panel";
import type { CitationRecord, ConversationMessage } from "../lib/contracts";

/**
 * BCP 47 tags for the language codes the pipeline records.
 *
 * The document is `lang="en"`, so an unmarked Tamil question is announced by a
 * screen reader with English pronunciation rules — unintelligible rather than
 * merely accented. Tanglish is Tamil written in Latin script, which no tag
 * describes; it is left unmarked rather than mislabelled as either language.
 */
const LANGUAGE_TAGS: Readonly<Record<string, string>> = {
  eng: "en",
  tam: "ta",
};

export function languageTag(language: string | null): string | undefined {
  return language === null ? undefined : LANGUAGE_TAGS[language];
}

type ConversationThreadProps = Readonly<{
  canReview: boolean;
  conversationId: string;
  messages: readonly ConversationMessage[];
  workspaceId: string;
}>;

export function ConversationThread({
  canReview,
  conversationId,
  messages,
  workspaceId,
}: ConversationThreadProps) {
  return (
    <ol className="thread">
      {messages.map((message) =>
        message.role === "user" ? (
          <QuestionTurn key={message.id} message={message} />
        ) : (
          <AnswerTurn
            canReview={canReview}
            conversationId={conversationId}
            key={message.id}
            message={message}
            workspaceId={workspaceId}
          />
        ),
      )}
    </ol>
  );
}

function QuestionTurn({ message }: Readonly<{ message: ConversationMessage }>) {
  // A Tanglish question is stored with its Tamil-script reading. Showing it
  // tells the asker how their question was actually interpreted, which is the
  // difference between "no results" and "you searched for something else".
  const showsReading =
    message.language === "tanglish" &&
    message.transliterated_content !== null &&
    message.transliterated_content !== message.content;

  return (
    <li className="turn" data-role="user">
      <h3 className="turn-label">You asked</h3>
      <p className="question-text" lang={languageTag(message.language)}>
        {message.content}
      </p>
      {showsReading ? (
        <p className="question-reading">
          Read as: <span lang="ta">{message.transliterated_content}</span>
        </p>
      ) : null}
    </li>
  );
}

function AnswerTurn({
  canReview,
  conversationId,
  message,
  workspaceId,
}: Readonly<{
  canReview: boolean;
  conversationId: string;
  message: ConversationMessage;
  workspaceId: string;
}>) {
  const copy = describeAnswer(message.decision, message.answer_status);
  // The pipeline's own reasons, after our wording — they are specific to this
  // question in a way fixed copy cannot be. Both fields may hold a stable
  // machine code rather than prose, and the two commonly hold the *same* reason,
  // so each is translated and repeats are dropped.
  const reasons = [
    ...new Set(
      [message.decision_reason, message.abstention_reason]
        .map(explainReason)
        .filter((reason): reason is string => reason !== null),
    ),
  ];
  const citationsByClaim = new Map<number, CitationRecord>(
    message.citations.map((citation) => [citation.claim_index, citation]),
  );

  return (
    <li className="turn" data-role="assistant" data-tone={copy.tone}>
      <div className="answer-heading">
        <h3 className="turn-label">Answer</h3>
        <AnswerBadge decision={message.decision} status={message.answer_status} />
      </div>

      <p className="answer-explanation">{copy.explanation}</p>
      {reasons.map((reason) => (
        <p className="answer-reason" key={reason}>
          {reason}
        </p>
      ))}

      {/* A composed answer is one `- claim` line per supported statement. The
          newlines are the structure, so they are preserved rather than collapsed
          into a run-on paragraph by normal whitespace handling. */}
      <p className="answer-text" lang={languageTag(message.language)}>
        {message.content}
      </p>

      {message.confidence === null ? null : <ConfidenceMeter confidence={message.confidence} />}

      {message.claims.length > 0 ? (
        <section aria-label="Supported statements" className="claims">
          <ol className="claim-list">
            {message.claims.map((claim, position) => {
              // Matched on the claim's own index, never on list position: the
              // API sorts claims by index but serializes citations from an
              // unordered relationship, so pairing by position would eventually
              // show one claim's passage as if it proved another.
              const citation = citationsByClaim.get(claim.claim_index);
              return (
                <li className="claim" key={`${message.id}-${claim.claim_index}`}>
                  <p className="claim-text">{claim.claim_text}</p>
                  <p className="claim-meta">
                    <VerdictBadge verdict={claim.verdict} />
                    <span className="claim-verifier">Checked by {claim.verifier}</span>
                  </p>
                  {citation === undefined ? null : (
                    <EvidencePanel citation={citation} index={position} workspaceId={workspaceId} />
                  )}
                </li>
              );
            })}
          </ol>
        </section>
      ) : (
        <p className="claims-empty">
          No statement here is backed by a citation, so nothing in this answer should be relied on.
        </p>
      )}

      {canReview ? (
        <AnswerFeedback
          conversationId={conversationId}
          messageId={message.id}
          workspaceId={workspaceId}
        />
      ) : null}
    </li>
  );
}
