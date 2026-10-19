/** Syntax highlighting for fenced code: the languages people actually write, loaded once and cached. */

import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import clojure from "highlight.js/lib/languages/clojure";
import cmake from "highlight.js/lib/languages/cmake";
import coffeescript from "highlight.js/lib/languages/coffeescript";
import cpp from "highlight.js/lib/languages/cpp";
import crystal from "highlight.js/lib/languages/crystal";
import csharp from "highlight.js/lib/languages/csharp";
import css from "highlight.js/lib/languages/css";
import d from "highlight.js/lib/languages/d";
import dart from "highlight.js/lib/languages/dart";
import diff from "highlight.js/lib/languages/diff";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import dos from "highlight.js/lib/languages/dos";
import elixir from "highlight.js/lib/languages/elixir";
import elm from "highlight.js/lib/languages/elm";
import erlang from "highlight.js/lib/languages/erlang";
import fsharp from "highlight.js/lib/languages/fsharp";
import go from "highlight.js/lib/languages/go";
import gradle from "highlight.js/lib/languages/gradle";
import graphql from "highlight.js/lib/languages/graphql";
import groovy from "highlight.js/lib/languages/groovy";
import haskell from "highlight.js/lib/languages/haskell";
import http from "highlight.js/lib/languages/http";
import ini from "highlight.js/lib/languages/ini";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import julia from "highlight.js/lib/languages/julia";
import kotlin from "highlight.js/lib/languages/kotlin";
import latex from "highlight.js/lib/languages/latex";
import less from "highlight.js/lib/languages/less";
import lisp from "highlight.js/lib/languages/lisp";
import lua from "highlight.js/lib/languages/lua";
import makefile from "highlight.js/lib/languages/makefile";
import markdown from "highlight.js/lib/languages/markdown";
import matlab from "highlight.js/lib/languages/matlab";
import nginx from "highlight.js/lib/languages/nginx";
import nim from "highlight.js/lib/languages/nim";
import objectivec from "highlight.js/lib/languages/objectivec";
import ocaml from "highlight.js/lib/languages/ocaml";
import perl from "highlight.js/lib/languages/perl";
import php from "highlight.js/lib/languages/php";
import plaintext from "highlight.js/lib/languages/plaintext";
import powershell from "highlight.js/lib/languages/powershell";
import properties from "highlight.js/lib/languages/properties";
import protobuf from "highlight.js/lib/languages/protobuf";
import python from "highlight.js/lib/languages/python";
import r from "highlight.js/lib/languages/r";
import ruby from "highlight.js/lib/languages/ruby";
import rust from "highlight.js/lib/languages/rust";
import scala from "highlight.js/lib/languages/scala";
import scheme from "highlight.js/lib/languages/scheme";
import scss from "highlight.js/lib/languages/scss";
import shell from "highlight.js/lib/languages/shell";
import sql from "highlight.js/lib/languages/sql";
import swift from "highlight.js/lib/languages/swift";
import typescript from "highlight.js/lib/languages/typescript";
import vbnet from "highlight.js/lib/languages/vbnet";
import vim from "highlight.js/lib/languages/vim";
import wasm from "highlight.js/lib/languages/wasm";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

const LANGUAGES = {
  bash, c, clojure, cmake, coffeescript, cpp, crystal, csharp, css, d, dart, diff, dockerfile, dos, elixir, elm,
  erlang, fsharp, go, gradle, graphql, groovy, haskell, http, ini, java, javascript, json, julia, kotlin, latex,
  less, lisp, lua, makefile, markdown, matlab, nginx, nim, objectivec, ocaml, perl, php, plaintext, powershell,
  properties, protobuf, python, r, ruby, rust, scala, scheme, scss, shell, sql, swift, typescript, vbnet, vim,
  wasm, xml, yaml,
};

for (const [name, definition] of Object.entries(LANGUAGES)) {
  hljs.registerLanguage(name, definition);
}

/** The names people put after the fence that the definitions do not already claim. */
const ALIASES: Record<string, string> = {
  jsonc: "json",
  json5: "json",
  jsonl: "json",
  mjs: "javascript",
  cjs: "javascript",
  node: "javascript",
  vue: "xml",
  svelte: "xml",
  astro: "xml",
  xhtml: "xml",
  plist: "xml",
  console: "bash",
  terminal: "bash",
  shellsession: "shell",
  zsh: "bash",
  fish: "bash",
  ksh: "bash",
  sh: "bash",
  patch: "diff",
  tex: "latex",
  bibtex: "latex",
  docker: "dockerfile",
  make: "makefile",
  mk: "makefile",
  toml: "ini",
  conf: "ini",
  cfg: "ini",
  env: "properties",
  dotenv: "properties",
  pwsh: "powershell",
  ps1: "powershell",
  bat: "dos",
  cmd: "dos",
  batch: "dos",
  "c#": "csharp",
  "f#": "fsharp",
  "c++": "cpp",
  hpp: "cpp",
  cc: "cpp",
  cxx: "cpp",
  h: "c",
  objc: "objectivec",
  "objective-c": "objectivec",
  golang: "go",
  rs: "rust",
  rb: "ruby",
  py: "python",
  python3: "python",
  kt: "kotlin",
  kts: "kotlin",
  gradlew: "gradle",
  hs: "haskell",
  ex: "elixir",
  exs: "elixir",
  erl: "erlang",
  pl: "perl",
  jl: "julia",
  proto: "protobuf",
  gql: "graphql",
  md: "markdown",
  yml: "yaml",
  html: "xml",
  htm: "xml",
  svg: "xml",
  text: "plaintext",
  txt: "plaintext",
  plain: "plaintext",
  none: "plaintext",
  clj: "clojure",
  cljs: "clojure",
  ml: "ocaml",
  vb: "vbnet",
  nimrod: "nim",
  rkt: "scheme",
  el: "lisp",
  cl: "lisp",
};

/** Return the highlighter's name for a fence label, or `null` for a language we cannot colour. */
export function resolveLanguage(label: string): string | null {
  const name = label.trim().toLowerCase();
  if (!name) {
    return null;
  }
  const direct = hljs.getLanguage(name);
  if (direct !== undefined) {
    return name;
  }
  const alias = ALIASES[name];
  if (alias !== undefined && hljs.getLanguage(alias) !== undefined) {
    return alias;
  }
  return null;
}

const CACHE = new Map<string, string>();
const CACHE_LIMIT = 300;

/** What an unlabelled fence is guessed among: the languages answers are mostly written in. */
const GUESSES = ["python", "javascript", "typescript", "bash", "json", "yaml", "rust", "go", "java", "c", "cpp", "sql", "xml", "css"];
/** How sure the guess must be, and the longest block it is tried on (a block still streaming is tried at every delta). */
const GUESS_RELEVANCE = 4;
const GUESS_LIMIT = 6000;

/** Highlight code as HTML, or return `null` when the language is unknown. A bad snippet never throws. */
export function highlight(code: string, label: string): string | null {
  const language = resolveLanguage(label);
  if (language === null) {
    return label.trim() === "" ? guess(code) : null;
  }
  const key = `${language}\u0000${code}`;
  const hit = CACHE.get(key);
  if (hit !== undefined) {
    return hit;
  }
  let html: string;
  try {
    html = hljs.highlight(code, { language, ignoreIllegals: true }).value;
  } catch {
    return null;
  }
  remember(key, html);
  return html;
}

/** Colour a block that names no language when the highlighter is quite sure which one it is; otherwise leave it plain. */
function guess(code: string): string | null {
  if (code.length < 12 || code.length > GUESS_LIMIT || !code.includes("\n")) {
    return null;
  }
  const key = `\u0000guess\u0000${code}`;
  const hit = CACHE.get(key);
  if (hit !== undefined) {
    return hit || null;
  }
  let html = "";
  try {
    const result = hljs.highlightAuto(code, GUESSES);
    html = result.relevance >= GUESS_RELEVANCE ? result.value : "";
  } catch {
    html = "";
  }
  remember(key, html);
  return html || null;
}

function remember(key: string, html: string): void {
  if (CACHE.size >= CACHE_LIMIT) {
    const oldest = CACHE.keys().next().value;
    if (oldest !== undefined) {
      CACHE.delete(oldest);
    }
  }
  CACHE.set(key, html);
}

/** The languages that have a colour scheme, for the tests and the guide. */
export function highlightedLanguages(): string[] {
  return hljs.listLanguages();
}
