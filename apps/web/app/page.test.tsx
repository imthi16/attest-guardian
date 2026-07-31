import { render, screen } from "@testing-library/react";

/**
 * `next/font/google` is rewritten by the Next.js SWC transform at build time,
 * and vitest does not run that transform — the loaders are plain undefined here.
 * The stub returns the `variable` shape the page actually reads, so a font
 * added to the page without a stub fails loudly rather than silently.
 */
vi.mock("next/font/google", () => {
  const loader = (variable: string) => () => ({ className: `stub${variable}`, variable });
  return {
    Bricolage_Grotesque: loader("--lp-font-display"),
    IBM_Plex_Sans: loader("--lp-font-body"),
    IBM_Plex_Mono: loader("--lp-font-mono"),
    Noto_Serif_Tamil: loader("--lp-font-tamil"),
  };
});

import HomePage from "./page";

describe("HomePage", () => {
  it("states the product's claim and both ways to start", () => {
    render(<HomePage />);

    expect(
      screen.getByRole("heading", { name: /every answer arrives with its coordinates/i }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /create account/i })[0]).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getAllByRole("link", { name: /sign in/i })[0]).toHaveAttribute("href", "/login");
  });

  /**
   * The hero's whole argument is that the offsets are true of the text beside
   * them. They are computed from the passage rather than written down, so this
   * checks the rendered label against the rendered passage — if the two ever
   * disagree, the page is making the one claim it exists to disprove.
   */
  it("measures the evidence span at offsets that hold for the passage shown", () => {
    const { container } = render(<HomePage />);

    const passage = container.querySelector(".lp-passage");
    const span = container.querySelector(".lp-span");
    const measure = container.querySelector(".lp-span-measure");
    expect(passage).not.toBeNull();
    expect(span).not.toBeNull();
    expect(measure).not.toBeNull();

    const [start, end] = (measure?.textContent ?? "").split("–").map(Number);
    expect(Number.isInteger(start)).toBe(true);
    expect(Number.isInteger(end)).toBe(true);

    // The measure label sits inside the mark, so the quoted span is what remains.
    const quoted = (span?.textContent ?? "").replace(measure?.textContent ?? "", "");
    const passageText = (passage?.textContent ?? "").replace(measure?.textContent ?? "", "");

    expect(passageText.slice(start, end)).toBe(quoted);
    expect(end - start).toBe(quoted.length);
  });

  it("keeps the page's first heading its h1", () => {
    render(<HomePage />);

    const headings = screen.getAllByRole("heading");
    expect(headings[0]).toBe(screen.getByRole("heading", { level: 1 }));
  });

  it("marks Tamil text as Tamil so it is not read as English", () => {
    const { container } = render(<HomePage />);

    const tamil = container.querySelectorAll('[lang="ta"]');
    expect(tamil.length).toBeGreaterThan(0);
    for (const node of tamil) {
      expect(node.textContent).toMatch(/[஀-௿]/);
    }
  });

  it("gives refusal equal billing with the answered outcome", () => {
    const { container } = render(<HomePage />);

    expect(container.querySelector('[data-outcome="answered"]')).not.toBeNull();
    expect(container.querySelector('[data-outcome="refused"]')).not.toBeNull();
    expect(screen.getByText("No answer given")).toBeInTheDocument();
  });
});
