import { render, screen, within } from "@testing-library/react";

import { AccessNotice } from "./access-notice";

/**
 * A refused request must look refused. These cases assert the visitor always
 * sees a heading, guidance, the stable code, and a way out, never a blank
 * region that reads as "nothing here".
 */
describe("AccessNotice", () => {
  it("renders access denied for insufficient_role", () => {
    render(
      <AccessNotice
        code="insufficient_role"
        message="Your workspace role does not allow this action."
      />,
    );

    const alert = screen.getByRole("alert");
    expect(within(alert).getByRole("heading", { name: "Access denied" })).toBeInTheDocument();
    expect(alert).toHaveTextContent("Your workspace role does not allow this action.");
    expect(alert).toHaveTextContent("Ask an owner to raise your role.");
    expect(alert).toHaveTextContent("Reference: insufficient_role");
    expect(screen.getByRole("link", { name: "Back to workspaces" })).toHaveAttribute(
      "href",
      "/workspaces",
    );
  });

  it("renders not found for workspace_not_found", () => {
    render(
      <AccessNotice
        code="workspace_not_found"
        message="The workspace does not exist or you are not a member."
      />,
    );

    expect(screen.getByRole("heading", { name: "Workspace not found" })).toBeInTheDocument();
    // Non-membership and absence share one message on purpose: the API must not
    // disclose whether another tenant's workspace exists.
    expect(screen.getByRole("alert")).toHaveTextContent("or you are not a member");
  });

  it("explains a rate-limited request", () => {
    render(<AccessNotice code="rate_limited" message="Too many attempts; retry later." />);

    expect(screen.getByRole("heading", { name: "Too many attempts" })).toBeInTheDocument();
  });

  it("falls back to a generic refusal for an unmapped code", () => {
    render(<AccessNotice code="api_unreachable" message="The service is unavailable." />);

    expect(screen.getByRole("heading", { name: "Something went wrong" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: api_unreachable");
  });
});
