import { isValidElement, type ReactElement } from "react";

import RootLayout from "./layout";

// `suppressHydrationWarning` is a React-only prop: it never reaches the DOM, so
// rendering the tree and querying an attribute cannot see it. The layout is also
// the one component that returns <html>/<body>, which jsdom will not nest inside
// its own document. Both point at the same approach — call the component and
// inspect the element it returns.
function renderToElement(): ReactElement {
  const html = RootLayout({ children: null });
  if (!isValidElement(html)) {
    throw new Error("RootLayout did not return an element");
  }
  return html;
}

function bodyOf(html: ReactElement): ReactElement {
  const { children } = html.props as { children: unknown };
  if (!isValidElement(children)) {
    throw new Error("expected <html> to hold a single <body> element");
  }
  return children;
}

describe("RootLayout", () => {
  it("declares the document language", () => {
    expect(renderToElement().props).toMatchObject({ lang: "en" });
  });

  it("suppresses the hydration warning on <body> and nowhere else", () => {
    const html = renderToElement();
    const body = bodyOf(html);

    expect(body.type).toBe("body");
    expect(body.props).toMatchObject({ suppressHydrationWarning: true });

    // Scope is the entire point. Extensions inject their attributes onto <body>
    // before React hydrates; suppressing at <html> would cover the whole
    // document and hide real markup differences in the app's own output.
    expect(html.props).not.toMatchObject({ suppressHydrationWarning: true });
  });

  it("keeps the skip link first in the body", () => {
    const { children } = bodyOf(renderToElement()).props as { children: unknown[] };
    const [skipLink] = children;
    if (!isValidElement(skipLink)) {
      throw new Error("expected a skip link as the first child of <body>");
    }

    expect(skipLink.props).toMatchObject({ href: "#main-content" });
  });
});
