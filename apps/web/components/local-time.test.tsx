import { render, screen, waitFor } from "@testing-library/react";

import { LocalTime, formatInstant } from "./local-time";

describe("formatInstant", () => {
  it("renders an instant in the running environment's zone", () => {
    expect(formatInstant("2026-07-30T09:00:00Z")).toBe(
      new Date("2026-07-30T09:00:00Z").toLocaleString(),
    );
  });

  it("shows an unparseable value as it arrived rather than as Invalid Date", () => {
    expect(formatInstant("not a timestamp")).toBe("not a timestamp");
  });
});

describe("LocalTime", () => {
  it("keeps the machine-readable instant alongside the readable one", async () => {
    render(<LocalTime value="2026-07-30T09:00:00Z" />);

    const element = screen.getByText(
      (_, node) => node?.tagName === "TIME" && node.textContent !== "",
    );
    expect(element).toHaveAttribute("datetime", "2026-07-30T09:00:00Z");
    // The localized form replaces the raw instant once mounted; before that the
    // markup is the unambiguous UTC string, which is what a server renders and
    // what a reader without JavaScript is left with.
    await waitFor(() => {
      expect(element).toHaveTextContent(new Date("2026-07-30T09:00:00Z").toLocaleString());
    });
  });
});
