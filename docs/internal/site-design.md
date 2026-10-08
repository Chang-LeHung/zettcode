# Documentation and brand assets

## Local preview

Run `make docs` from the repository root. VitePress prints the local address;
the site is served below `/zettcode/`, matching GitHub Pages. English is at the
root and Simplified Chinese at `/zh/`. `make docs-build` checks dead links and
produces the static site; `make docs-preview` serves that build.

The existing Docs workflow builds changes under `docs/` on pull requests and
publishes them from `main`. Internal notes in this directory remain excluded.

## Design responsibilities

- `src/zettcode/app/brand.py` holds the single 15×10 pixel map and fixed brand
  palette used by every surface. There is no separate website interpretation.
  `docs/public/logo.svg` is generated from it: a green pixel robot
  with square eyes, side ears, and a warm heart. The navigation, favicon, and
  README use the same asset. Keep the silhouette recognizable at 16 and 32 px.
- `src/zettcode/app/ui/widgets/welcome.py` is the terminal interpretation.
  Its five-row, fifteen-column mark uses the same pixels as the website, with square
  eyes and a heart tapering to a single pixel rather than a blunt stem. It packs
  two pixels per cell without resampling the eyes, ears, or heart. Terminal
  fonts determine the physical cell proportions; the SVG preview uses 10×20
  cells and draws block glyphs as crisp-edged rectangles rather than font outlines.
  `WelcomeProcessor` groups the title, subtitle, and help hint beside the icon;
  narrow windows stack the labels underneath instead of clipping the icon's
  right edge. Both themes use the same mark; its margins stay transparent.
- `docs/.vitepress/navigation.ts` defines page order once, with English and
  Chinese labels. VitePress provides corresponding-page language switching.
- `docs/.vitepress/theme/home.ts` holds both translations of the homepage;
  `ProductHome.vue` owns the structure. Keep links locale-aware with `withBase`
  so GitHub Pages and local previews work identically.
- `custom.css` owns the light/dark guide palette and reading styles; `home.css`
  owns the responsive product homepage. No external fonts, tracking scripts,
  image-generation service, or new runtime dependency is needed.

The site is a user guide, not an implementation reference. Group pages by
first-time use, everyday operation, configuration/extensions, and help. Keep
page slugs stable, and add the Chinese counterpart when adding an English page.

Keep usage examples executable: model tables and optional config fragments are
loaded through the real config parser, MCP examples through the released server
config parser, and plugin command examples through registration and execution
in `tests/test_docs.py`. Use placeholder credentials and temporary directories,
never make billable calls in documentation tests. Verify model ids, context
limits, and image support against the endpoint's current official reference
when updating provider examples; the config parser cannot verify remote claims.

## Terminal preview

The homepage and both READMEs share `docs/public/terminal.svg`. It is an
**illustrative conversation rendered by the real TUI**, not a recording of an
API request. The caption says so explicitly. Do not publish invented speed or
usage measurements as benchmarks.

Regenerate it after changing the welcome or the transcript presentation:

```bash
uv run python docs/scripts/render_terminal.py --logo-output docs/public/logo.svg
```

The script builds an offline `ZettCodeApp`, uses temporary workspace/session
directories, labels the header with an illustrative path, seeds a fixed
conversation, paints the actual widgets, and
serializes the canvas. It never starts a provider or reads a user's sessions.
Pass `--output /path/to/terminal.svg` to write somewhere else. The working
directory is restored even if rendering fails. `--logo-output` regenerates the
navigation/README logo as well; tests compare both committed assets with their
generated output, so a terminal change cannot silently leave stale docs art.

## Review checklist

- Both homepages, both READMEs, and one guide page in each language.
- Light/dark palettes at desktop, tablet, and phone widths.
- Language switching on a guide page preserves its slug.
- Local search, menu labels, copy feedback, and image alt text are translated.
- Navigation and copy button work by keyboard; focus remains visible.
- Long tables and the terminal preview scroll inside their own containers.
- `npm run docs:build --prefix docs` and `make check` pass.
