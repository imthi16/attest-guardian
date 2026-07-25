/**
 * Labelled text field with explicit, announced validation messaging.
 *
 * The label is always associated with the control, and a field error is linked
 * through `aria-describedby` with `aria-invalid`, so assistive technology
 * reports the problem instead of silently failing validation.
 */
type FieldProps = Readonly<{
  autoComplete?: string;
  defaultValue?: string;
  error?: string;
  hint?: string;
  label: string;
  name: string;
  required?: boolean;
  type?: "email" | "password" | "text";
}>;

export function Field({
  autoComplete,
  defaultValue,
  error,
  hint,
  label,
  name,
  required = true,
  type = "text",
}: FieldProps) {
  const errorId = `${name}-error`;
  const hintId = `${name}-hint`;
  const describedBy = [hint === undefined ? null : hintId, error === undefined ? null : errorId]
    .filter((value): value is string => value !== null)
    .join(" ");

  return (
    <p className="field">
      <label htmlFor={name}>{label}</label>
      {hint === undefined ? null : (
        <span className="field-hint" id={hintId}>
          {hint}
        </span>
      )}
      <input
        aria-describedby={describedBy === "" ? undefined : describedBy}
        aria-invalid={error === undefined ? undefined : true}
        autoComplete={autoComplete}
        defaultValue={defaultValue}
        id={name}
        name={name}
        required={required}
        type={type}
      />
      {error === undefined ? null : (
        <span className="field-error" id={errorId}>
          {error}
        </span>
      )}
    </p>
  );
}
