"use client";

/**
 * A timestamp in the reader's own time zone.
 *
 * Formatting an instant on the server formats it in the *server's* zone, which
 * in a deployment is almost always UTC. The result is an unlabelled time that
 * looks local and is not — "last asked at 09:14" when it was 14:44 where the
 * reader is sitting. Only the browser knows the right zone, so the conversion
 * happens there.
 *
 * The server renders the raw ISO instant and the browser matches it during
 * hydration, then swaps in the localized form. A reader with JavaScript disabled
 * is therefore left with an unambiguous UTC timestamp rather than a misleading
 * one, and hydration never has two different strings to reconcile.
 */
import { useSyncExternalStore } from "react";

type LocalTimeProps = Readonly<{
  className?: string;
  /** An ISO 8601 instant from the API. */
  value: string;
}>;

export function formatInstant(value: string): string {
  const parsed = new Date(value);
  // An unparseable timestamp is shown as it arrived rather than as "Invalid
  // Date": the raw value is at least evidence of what the API returned.
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** The instant never changes underneath us, so there is nothing to subscribe to. */
const subscribe = () => () => {};

export function LocalTime({ className, value }: LocalTimeProps) {
  // Two snapshots rather than an effect: React renders the server one during
  // hydration and the client one afterwards, which is exactly the handover this
  // needs and keeps the two trees identical while they are being matched.
  const display = useSyncExternalStore(
    subscribe,
    () => formatInstant(value),
    () => value,
  );

  return (
    <time className={className} dateTime={value}>
      {display}
    </time>
  );
}
