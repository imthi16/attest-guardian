import {
  Bricolage_Grotesque,
  IBM_Plex_Mono,
  IBM_Plex_Sans,
  Noto_Serif_Tamil,
} from "next/font/google";
import Link from "next/link";

/**
 * The landing page is the one surface whose job is identity, so it carries its
 * own type and colour rather than the product's. Everything here is namespaced
 * `lp-`: `.hero`, `.eyebrow`, `.primary-button` and `SystemState` are shared with
 * seventeen product screens, and reskinning them here would reskin those.
 *
 * The fonts are loaded on this page rather than in the root layout for the same
 * reason — `next/font` scopes them to the element that carries the variable
 * class, so the product's typography is untouched.
 */
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--lp-font-display",
  display: "swap",
});
const body = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--lp-font-body",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--lp-font-mono",
  display: "swap",
});
const tamil = Noto_Serif_Tamil({
  subsets: ["tamil"],
  variable: "--lp-font-tamil",
  display: "swap",
});

/**
 * The passage, the claim it supports, and the span that proves it.
 *
 * All three come from `evaluation/datasets/corpus.json` — the versioned corpus
 * the platform is scored against, whose every passage is synthetic by
 * construction. The offsets are not written down anywhere: they are computed
 * from the string rendered on the page, so the number under the caliper is true
 * of the text above it or the page does not build.
 *
 * The span has to prove the *whole* claim on its own, since the page says it
 * does and nothing else. So it carries the action as well as the number: a
 * highlight reading only "ninety days written notice" leaves what the notice
 * ends unsaid, and this page's one job is to be the example that survives being
 * checked. The claim is worded down to what the highlight entails — "either
 * party" sits outside the span, so the claim does not say it, and every
 * substantive word of the claim is inside the span, which a test enforces.
 */
const PASSAGE = "Either party may terminate this agreement with ninety days written notice.";
const EVIDENCE = "terminate this agreement with ninety days written notice";
const CLAIM = "This agreement terminates on ninety days written notice.";

const spanStart = PASSAGE.indexOf(EVIDENCE);
const spanEnd = spanStart + EVIDENCE.length;

/** What the platform refuses to do, in the order a sceptic asks about them. */
const constraints = [
  {
    refusal: "Take an instruction from a document",
    detail:
      "Retrieved text is data, never a command. A file that tells the system to ignore its rules is quarantined during ingestion, and quarantine is terminal — there is no retry control at any role.",
  },
  {
    refusal: "Report a model's own confidence",
    detail:
      "Confidence is computed from retrieval score, rerank score, OCR confidence, and query overlap. A model's opinion of itself is not evidence and is never the number you see.",
  },
  {
    refusal: "Read across a workspace boundary",
    detail:
      "Scoping lives in the repository and retrieval layers and again in Postgres row-level security, not only on the route. A non-member gets 404, never 403 — the existence of a workspace is itself private.",
  },
  {
    refusal: "Answer from a document you withdrew",
    detail:
      "Archiving a document stops answers rather than hiding list rows. One predicate decides evidence eligibility, and lexical search, dense search, hydration, and citation provenance all ask it.",
  },
  {
    refusal: "Invent a quote",
    detail:
      "Opening a citation re-reads the stored text at the recorded offsets and refuses to return anything unless it matches. A paraphrase renders a failure notice where the passage would be.",
  },
];

export default function HomePage() {
  return (
    <main
      id="main-content"
      className={`lp ${display.variable} ${body.variable} ${mono.variable} ${tamil.variable}`}
    >
      <header className="lp-masthead">
        <p className="lp-wordmark">Attest&nbsp;Guardian</p>
        {/*
          Both masthead links are plain. The filled button is the page's one loud
          element, and spending it here — above the proof that earns it — left
          three of them competing on a page with a single thing to say.
        */}
        <nav className="lp-masthead-nav" aria-label="Account">
          <Link href="/login">Sign in</Link>
          <Link href="/register">Create account</Link>
        </nav>
      </header>

      {/*
        The claim is deliberately not a heading. It reads like one, but the page's
        first heading has to be the h1 below it, or a screen reader navigating by
        heading meets an h2 before the h1 that names the page.
      */}
      <section className="lp-proof" aria-label="A cited answer, taken apart">
        <p className="lp-label">One answer, taken apart</p>

        <p className="lp-claim">{CLAIM}</p>

        <figure className="lp-exhibit">
          <figcaption className="lp-provenance">
            <span>alpha-supply-agreement</span>
            <span aria-hidden="true">·</span>
            <span>page 4</span>
            <span aria-hidden="true">·</span>
            <span>Termination</span>
            <span aria-hidden="true">·</span>
            <span>eng</span>
          </figcaption>

          <p className="lp-passage">
            {PASSAGE.slice(0, spanStart)}
            <mark className="lp-span">
              {EVIDENCE}
              <span className="lp-span-measure" aria-hidden="true">
                {spanStart}–{spanEnd}
              </span>
            </mark>
            {PASSAGE.slice(spanEnd)}
          </p>
        </figure>

        <p className="lp-exhibit-note">
          {/*
            Both spaces touching the expression containers are explicit. Adjacent
            to one the JSX transform drops a plain space, and the sentence renders
            as "characters 17–73of that page" and "nothing else.Opening".

            "Characters", never bytes. A citation resolves as `content[start:end]`
            over the stored text, and Python slices strings by code point — on a
            Tamil passage a byte range of the same numbers would cut somewhere
            else entirely, which is the failure this page claims not to have.
          */}
          The claim above is supported by characters {spanStart}–{spanEnd}
          {" of that page, and nothing else. "}
          Opening the citation re-reads the stored text at those character offsets — what you see is
          the document&apos;s text, not the model&apos;s recollection of it.
        </p>
      </section>

      <section className="lp-thesis" aria-labelledby="lp-thesis-title">
        <h1 id="lp-thesis-title">Every answer arrives with its coordinates.</h1>
        <p className="lp-lede">
          Attest Guardian answers questions about your Tamil, Tanglish, and English documents, and
          attaches the document, page, and character range each statement came from. When the
          evidence will not support an answer, it says so instead of writing one.
        </p>
        <p className="lp-actions">
          <Link className="lp-cta" href="/register">
            Create account
          </Link>
          <Link className="lp-cta-ghost" href="/login">
            Sign in
          </Link>
        </p>
      </section>

      <section className="lp-outcomes" aria-labelledby="lp-outcomes-title">
        <div className="lp-section-head">
          <p className="lp-label">Two ways this ends</p>
          <h2 id="lp-outcomes-title">Refusing is a result, not a failure.</h2>
        </div>

        <div className="lp-outcome-pair">
          <article className="lp-outcome" data-outcome="answered">
            <p className="lp-outcome-verdict">Answered</p>
            <p className="lp-outcome-copy">
              Every statement below is supported by a citation you can open.
            </p>
            <p className="lp-outcome-meta">
              <span className="lp-chip">Supported</span>
              <span>Checked by entailment-verifier-v1</span>
            </p>
          </article>

          <article className="lp-outcome" data-outcome="refused">
            <p className="lp-outcome-verdict">No answer given</p>
            <p className="lp-outcome-copy">
              The evidence was not sufficient to support an answer, so none was produced. Nothing
              here is a guess.
            </p>
            <p className="lp-outcome-meta">
              <span className="lp-chip">Confidence 0%</span>
              <span>Read that as an absence, not a score</span>
            </p>
          </article>
        </div>
      </section>

      <section className="lp-tamil" aria-labelledby="lp-tamil-title">
        <div className="lp-section-head">
          <p className="lp-label">Tamil is material, not a locale</p>
          <h2 id="lp-tamil-title">A vowel sign is not a word boundary.</h2>
        </div>

        <div className="lp-tamil-body">
          <div className="lp-shatter" role="group" aria-labelledby="lp-shatter-title">
            <p id="lp-shatter-title" className="lp-shatter-title">
              What the usual tokenizer does to one Tamil word
            </p>
            <p className="lp-shatter-row">
              <span className="lp-shatter-tag">kept</span>
              <span lang="ta" className="lp-tamil-word">
                விமான
              </span>
            </p>
            <p className="lp-shatter-row" data-broken="true">
              <span className="lp-shatter-tag">shattered</span>
              <span lang="ta" className="lp-tamil-word">
                <span>வ</span>
                <span>ம</span>
                <span>ன</span>
              </span>
            </p>
          </div>

          <div className="lp-tamil-prose">
            <p>
              Python&apos;s <code>\w</code> excludes the Unicode mark categories, and a Tamil vowel
              sign is a spacing combining mark. The tokenizer everyone reaches for therefore drops
              the vowel signs and returns bare consonants — two unrelated Tamil passages then share
              most of their tokens, and every lexical score built on them inflates without saying
              so.
            </p>
            <p>
              That defect reached generation, verification, reranking, and embeddings at once,
              because it is one idiom repeated in five places. Tamil and Tanglish are read as
              themselves here, and the corpus is scored in all three languages.
            </p>
            <p lang="ta" className="lp-quote-tamil">
              ஊழியர் விடுப்பு ஒவ்வொரு மாதமும் சேர்க்கப்படும்.
            </p>
            <p className="lp-quote-tanglish">
              Payment thirty days la pannanum, illena two percent penalty varum.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-constraints" aria-labelledby="lp-constraints-title">
        <div className="lp-section-head">
          <p className="lp-label">Constraints</p>
          <h2 id="lp-constraints-title">What it will not do.</h2>
        </div>

        <ul className="lp-constraint-list">
          {constraints.map((constraint) => (
            <li key={constraint.refusal}>
              <p className="lp-constraint-refusal">{constraint.refusal}</p>
              <p className="lp-constraint-detail">{constraint.detail}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="lp-close" aria-labelledby="lp-close-title">
        <h2 id="lp-close-title">Ask something you already know the answer to.</h2>
        <p className="lp-close-copy">
          It is the fastest way to find out whether a system is worth trusting with the questions
          you don&apos;t.
        </p>
        <p className="lp-actions">
          <Link className="lp-cta" href="/register">
            Create account
          </Link>
          <Link className="lp-cta-ghost" href="/login">
            Sign in
          </Link>
        </p>
      </section>
    </main>
  );
}
