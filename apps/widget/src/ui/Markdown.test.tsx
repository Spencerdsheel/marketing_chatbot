import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

let container: HTMLDivElement;
let root: Root;

function render(text: string): HTMLDivElement {
  act(() => {
    root.render(<Markdown text={text} />);
  });
  return container;
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
});

describe("Markdown", () => {
  it("renders **bold** as a <strong> element", () => {
    const el = render("this is **bold** text");
    const strong = el.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong?.textContent).toBe("bold");
  });

  it("renders *italic* as an <em> element", () => {
    const el = render("this is *italic* text");
    const em = el.querySelector("em");
    expect(em).not.toBeNull();
    expect(em?.textContent).toBe("italic");
  });

  it("renders inline `code` as a <code> element", () => {
    const el = render("run `npm install` first");
    const code = el.querySelector("code");
    expect(code).not.toBeNull();
    expect(code?.textContent).toBe("npm install");
  });

  it("autolinks a bare URL with rel=noopener noreferrer and target=_blank", () => {
    const el = render("see https://example.com/docs for more");
    const link = el.querySelector("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("href")).toBe("https://example.com/docs");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link?.getAttribute("target")).toBe("_blank");
  });

  it("renders an <img onerror> payload as literal visible text with NO <img> element created", () => {
    const el = render('click here <img src=x onerror=alert(1)> to continue');
    expect(el.querySelector("img")).toBeNull();
    expect(el.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("renders a <script> payload as literal visible text with NO <script> element created", () => {
    const el = render("hello <script>alert(1)</script> world");
    expect(el.querySelector("script")).toBeNull();
    expect(el.textContent).toContain("<script>alert(1)</script>");
  });

  it("renders a stray closing tag as literal text with no DOM injection", () => {
    const el = render("broken markup </div><div>injected</div>");
    // No element should be created purely from the reply text beyond the
    // component's own <p> wrapper — the tags must appear as literal text.
    expect(el.textContent).toContain("</div><div>injected</div>");
  });

  it("separates blank-line paragraphs into distinct <p> elements", () => {
    const el = render("first paragraph\n\nsecond paragraph");
    const paragraphs = el.querySelectorAll("p.cw-md-paragraph");
    expect(paragraphs.length).toBe(2);
    expect(paragraphs[0]?.textContent).toBe("first paragraph");
    expect(paragraphs[1]?.textContent).toBe("second paragraph");
  });
});
