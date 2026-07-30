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
import { AnswerBadge, ConfidenceMeter, VerdictBadge, describeAnswer } from "./answer-state";
import { AnswerFeedback } from "./answer-feedback";
import { EvidencePanel } from "./evidence-panel";
import type { ConversationMessage } from "../lib/contracts";

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
      <p className="question-text">{message.content}</p>
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
  return (
    <li className="turn" data-role="assistant" data-tone={copy.tone}>
      <div className="answer-heading">
        <h3 className="turn-label">Answer</h3>
        <AnswerBadge decision={message.decision} status={message.answer_status} />
      </div>

      <p className="answer-explanation">{copy.explanation}</p>
      {/* The pipeline's own reason, when it gave one, after our wording — it is
          specific to this question in a way fixed copy cannot be. */}
      {message.decision_reason === null ? null : (
        <p className="answer-reason">{message.decision_reason}</p>
      )}
      {message.abstention_reason === null ? null : (
        <p className="answer-reason">{message.abstention_reason}</p>
      )}

      <p className="answer-text" lang={message.language ?? undefined}>
        {message.content}
      </p>

      {message.confidence === null ? null : <ConfidenceMeter confidence={message.confidence} />}

      {message.claims.length > 0 ? (
        <section aria-label="Supported statements" className="claims">
          <ol className="claim-list">
            {message.claims.map((claim, position) => (
              <li className="claim" key={`${message.id}-${claim.claim_index}`}>
                <p className="claim-text">{claim.claim_text}</p>
                <p className="claim-meta">
                  <VerdictBadge verdict={claim.verdict} />
                  <span className="claim-verifier">Checked by {claim.verifier}</span>
                </p>
                {message.citations[position] === undefined ? null : (
                  <EvidencePanel
                    citation={message.citations[position]}
                    index={position}
                    workspaceId={workspaceId}
                  />
                )}
              </li>
            ))}
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
