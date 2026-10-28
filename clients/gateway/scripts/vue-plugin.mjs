/** An esbuild plugin for Vue single-file components: script, template (to a render function) and styles. */

import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { dirname, relative } from "node:path";
import { compileScript, compileStyle, compileTemplate, parse } from "vue/compiler-sfc";
import { transform } from "esbuild";

/**
 * Compile `.vue` files. Templates become render functions at build time, so the bundle carries Vue's runtime only:
 * nothing is compiled in the webview and its content security policy needs no `unsafe-eval`.
 *
 * @param {{ cssFile?: string }} options Where the components' styles are written, ordered by file path (so the cascade between components follows their names); omit to drop them.
 */
export function vuePlugin(options = {}) {
  /** @type {Map<string, string>} */
  const styles = new Map();
  return {
    name: "vue-sfc",
    setup(build) {
      build.onStart(() => styles.clear());
      build.onLoad({ filter: /\.vue$/ }, async (args) => {
        const source = await readFile(args.path, "utf8");
        const { descriptor, errors } = parse(source, { filename: args.path });
        if (errors.length > 0) {
          return { errors: errors.map((error) => ({ text: error.message, location: { file: args.path } })) };
        }
        const id = createHash("sha256").update(relative(process.cwd(), args.path)).digest("hex").slice(0, 8);
        let code;
        let lang = "js";
        if (descriptor.scriptSetup || descriptor.script) {
          lang = descriptor.scriptSetup?.lang ?? descriptor.script?.lang ?? "js";
          const script = compileScript(descriptor, {
            id,
            isProd: true,
            inlineTemplate: true,
            templateOptions: { compilerOptions: { isTS: lang === "ts" } },
          });
          code = script.content;
        } else if (descriptor.template) {
          const template = compileTemplate({ id, filename: args.path, source: descriptor.template.content, isProd: true });
          if (template.errors.length > 0) {
            return { errors: template.errors.map((error) => ({ text: String(error), location: { file: args.path } })) };
          }
          code = `${template.code}\nexport default { render }`;
        } else {
          code = "export default {}";
        }
        descriptor.styles.forEach((style, index) => {
          const compiled = compileStyle({ source: style.content, filename: args.path, id: `data-v-${id}`, scoped: false });
          if (compiled.errors.length > 0) {
            throw compiled.errors[0];
          }
          styles.set(`${args.path}#${index}`, `/* ${relative(process.cwd(), args.path)} */\n${compiled.code}\n`);
        });
        const result = await transform(code, { loader: lang === "ts" ? "ts" : "js", sourcefile: args.path });
        return { contents: result.code, loader: "js", resolveDir: dirname(args.path) };
      });
      build.onEnd(async () => {
        if (options.cssFile) {
          await writeFile(
            options.cssFile,
            [...styles.entries()]
              .sort(([left], [right]) => left.localeCompare(right))
              .map(([, css]) => css)
              .join("\n"),
          );
        }
      });
    },
  };
}

/** The compile-time flags Vue's runtime reads; the options API and the devtools are not shipped. */
export const VUE_DEFINES = {
  __VUE_OPTIONS_API__: "false",
  __VUE_PROD_DEVTOOLS__: "false",
  __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: "false",
  "process.env.NODE_ENV": '"production"',
};
