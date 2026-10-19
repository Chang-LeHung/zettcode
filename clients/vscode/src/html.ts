/** The chat webview's document: an empty mount point, the style sheets, and the one script that builds the view. */

export interface ChatHtmlOptions {
  /** The style sheets' webview URIs, in the order they apply. */
  styles: string[];
  /** The bundled webview script's URI. */
  script: string;
  /** `webview.cspSource`, the only root the page may load from. */
  cspSource: string;
  /** The one script nonce. */
  nonce: string;
}

/** Return the document the webview program mounts into. */
export function chatHtml(options: ChatHtmlOptions): string {
  const links = options.styles.map((href) => `<link rel="stylesheet" href="${href}">`).join("\n");
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${options.cspSource} data:; style-src ${options.cspSource}; script-src 'nonce-${options.nonce}'; font-src ${options.cspSource};">
${links}
<title>ZettCode</title>
</head>
<body>
<div id="app"></div>
<script nonce="${options.nonce}" src="${options.script}"></script>
</body>
</html>`;
}
