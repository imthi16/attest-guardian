/**
 * Accessible feedback banner for stable API error codes and confirmations.
 *
 * Errors are announced assertively and receive focus so keyboard and screen
 * reader users are not left guessing why a submission did nothing. The stable
 * code is rendered alongside the message so support and tests can rely on it.
 */
"use client";

import { useEffect, useRef } from "react";

export type FeedbackTone = "error" | "notice" | "success";

type FeedbackProps = Readonly<{
  code?: string;
  id?: string;
  message: string;
  tone: FeedbackTone;
}>;

export function Feedback({ code, id, message, tone }: FeedbackProps) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (tone === "error") {
      container.current?.focus();
    }
  }, [tone, message]);

  return (
    <div
      className="feedback"
      data-tone={tone}
      id={id}
      ref={container}
      role={tone === "error" ? "alert" : "status"}
      tabIndex={tone === "error" ? -1 : undefined}
    >
      <p className="feedback-message">{message}</p>
      {code === undefined ? null : <p className="feedback-code">Reference: {code}</p>}
    </div>
  );
}
