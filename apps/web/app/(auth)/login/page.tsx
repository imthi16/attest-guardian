import Link from "next/link";
import { redirect } from "next/navigation";

import { loginAction } from "../../auth-actions";
import { safeRedirectTarget } from "../../form-state";
import { CredentialForm } from "../../../components/credential-form";
import { Feedback } from "../../../components/feedback";
import { readSession } from "../../../lib/session";

export const metadata = { title: "Sign in — Attest Guardian" };

type LoginPageProps = Readonly<{
  searchParams: Promise<Readonly<{ expired?: string; next?: string; registered?: string }>>;
}>;

/**
 * Sign-in page. An existing session skips the form, so a signed-in visitor is
 * never asked for credentials again; `next` is sanitized before use.
 */
export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const nextPath = safeRedirectTarget(params.next);
  if ((await readSession()) !== null) {
    redirect(nextPath);
  }

  return (
    <main className="auth-main" id="main-content">
      <section aria-labelledby="login-title" className="auth-card">
        <p className="eyebrow">ATTEST GUARDIAN</p>
        <h1 id="login-title">Sign in</h1>
        <p className="auth-copy">
          Evidence-grounded answers require an authorized workspace. Sessions are held in
          server-side cookies, never in browser storage.
        </p>
        <p className="tamil-sample" lang="ta">
          உங்கள் பணியிடத்தில் நுழையுங்கள்.
        </p>

        {params.registered === "1" ? (
          <Feedback message="Account created. Sign in to continue." tone="success" />
        ) : null}
        {params.expired === "1" ? (
          <Feedback
            code="session_expired"
            message="Your session expired. Please sign in again."
            tone="notice"
          />
        ) : null}

        <CredentialForm action={loginAction} mode="login" nextPath={nextPath} />

        <p className="auth-alternate">
          No account yet? <Link href="/register">Create one</Link>.
        </p>
      </section>
    </main>
  );
}
