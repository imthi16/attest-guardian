import Link from "next/link";
import { redirect } from "next/navigation";

import { registerAction } from "../../auth-actions";
import { CredentialForm } from "../../../components/credential-form";
import { readSession } from "../../../lib/session";

export const metadata = { title: "Create account — Attest Guardian" };

/** Signup page; a signed-in visitor is sent to their workspaces instead. */
export default async function RegisterPage() {
  if ((await readSession()) !== null) {
    redirect("/workspaces");
  }

  return (
    <main className="auth-main" id="main-content">
      <section aria-labelledby="register-title" className="auth-card">
        <p className="eyebrow">ATTEST GUARDIAN</p>
        <h1 id="register-title">Create your account</h1>
        <p className="auth-copy">
          You will be added to workspaces by their owners or admins. Membership decides which
          documents can ever be used as evidence for your questions.
        </p>

        <CredentialForm action={registerAction} mode="register" />

        <p className="auth-alternate">
          Already registered? <Link href="/login">Sign in</Link>.
        </p>
      </section>
    </main>
  );
}
