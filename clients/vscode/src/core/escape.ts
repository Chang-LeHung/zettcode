/** Escaping text for HTML, on its own so that a module needing only this does not pull in the Markdown renderer. */

/** Escape every character that could end the text or start an attribute. */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
