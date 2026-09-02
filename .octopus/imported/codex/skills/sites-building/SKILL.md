---
name: sites-building
description: Use Sites to build websites, including landing pages, portfolios, dashboards, portals, trackers, hubs, and internal tools. Always use Sites when the project contains `.openai/hosting.json`.
---

# Sites building

Build the complete requested site, validate it, then use `sites-hosting`
unless the user explicitly asks to keep it local.

## Communicate clearly

Assume the user is a nontechnical knowledge worker. Talk about their site,
choices, progress, and results. Keep tools, commands, files, runtimes, browser
software, permissions, dependencies, source control, credentials, IDs, builds,
and deployment internals out of user-facing messages unless the user asks or
must take action.

Use no more than one short update for each user-visible phase: preparing the
site, building it, and publishing. If a phase takes longer
than 60 seconds, give one plain-language update. Keep recoverable technical
problems private; say only that you hit a problem and are trying another method.

Ask one concise group of up to three discovery questions only when important
context is missing and the unresolved details would materially affect the
site's functionality or force a risky assumption. Otherwise proceed immediately
with best judgment. Do not generate design options or pause for a visual
selection unless the user explicitly asks to compare designs.

## Choose the execution path

Use the **one-shot fast path** only when all of these are true:

- this is a new site in an empty or projectless workspace;
- one route can satisfy the request;
- the request does not require D1, R2, uploads, app-owned authentication,
  external connectors, or browser UI QA; and
- the normal deliverable is a private deployed URL.

Use the **capability path** otherwise. This includes existing-site changes,
multi-route sites, persistent data, uploads, authentication, external data, and
requested browser testing.

## Use imagery purposefully

Avoid model-authored SVGs in finished sites, including inline SVG
illustrations. Prefer strong typography, color, layout, CSS shapes, and existing
icon components when imagery is unnecessary. When a site needs real imagery,
prefer suitable images found through web image search. Use `imagegen` if and
only if original imagery is important and a suitable existing image is
unavailable; generation adds latency, so keep it purposeful and limited.

## Start new projects immediately

For a new site in an empty or projectless workspace, make setup the first task
action. Run this plugin's root-level `scripts/init-site.sh` with `$PWD` as its
target and retain the session until installation completes. As soon as the
copied starter files exist, inspect the minimum required files and begin the
bounded first product slice below while installation continues. Do not run a
second initializer.

In a visible foreground thread, start `npm run dev` in a retained session as
soon as setup finishes, but keep the browser closed until the **First meaningful
preview** gate below passes. The development server may render the starter
loading skeleton before that first product-specific compile, but the skeleton
is a fail-safe only and must never be the intended browser handoff. Keep the
development server alive through build and hosting.

In a delegated, background, or invisible thread, initialize normally but do
not start a browser-only preview unless the task otherwise needs the server.

## First meaningful preview

Treat the local preview as an early milestone in both execution paths. In a
visible foreground thread, open it as soon as, but not before, all of these are
true:

- the route contains the smallest coherent slice that lets a reasonable person
  recognize the requested site and its intended visual direction;
- it includes the primary product surface or layout and representative,
  product-specific content rather than an untouched starter, generic skeleton,
  blank page, or loading-only state;
- the primary affordance is visible when the requested experience is
  interaction-led; and
- the development server has successfully compiled the slice and the route
  responds without a blocking runtime error.

The slice may be static or partially inert. Keep it intentionally bounded and
defer secondary routes, complete data models, exhaustive interactions,
responsive refinements, animation, polish, and advanced capabilities until
after the handoff unless one is required for recognition, security, or a
successful render. Work on the slice while installation runs when possible.

For a new site, replace the `SkeletonPreview` render and temporary
`codex-preview` metadata marker as part of the slice. Keep the skeleton in the
bundled starter itself: it is a fail-safe if a preview is opened unexpectedly
early, not product UI. Cleanup of the now-unused `app/_sites-preview` files and
dependency may happen after the handoff, but must finish before final
validation.

Once the bounded slice is applied, make no further planned product-source edits
before the handoff. Fix only compilation or blocking runtime failures, then make
one lightweight non-browser request to the exact Local URL printed by the
development server to force the current route to render. Require a successful
compile and non-error response, but do not inspect the response body as visual
QA. Then use `open_in_codex` to show the first working version without waiting for the complete Site or a deployment.
Establish a stable browser-tab ID from the first preview and reuse it as the Site's single continuous user-facing view through HMR, publishing, and any later fixes.

For an existing site, use its current coherent experience immediately when it
still represents the requested product and compiles. If the request changes
the primary direction, apply only the smallest representative part first.
Preserve the last working content while changes compile; never replace an
existing site with the starter skeleton.

## One-shot build

After setup and any necessary clarification, show the first meaningful preview,
then build and deploy the complete site in one focused pass.

1. Start by inspecting `app/page.tsx`, `app/layout.tsx`, `app/globals.css`, and
   `.openai/hosting.json`. Read other files only when the implementation needs
   them. Avoid broad scans and speculative research. Preserve the package
   manager and lockfile.
2. Apply the smallest coherent product slice and complete the **First meaningful
   preview** handoff above before broadening the implementation. For a genuinely
   trivial request, the complete implementation may itself be that slice; do
   not manufacture extra edits merely to demonstrate HMR.
3. Reuse the retained setup, development server, and browser tab, then make one
   complete product patch. Prefer one page component and one
   stylesheet. Include all requested content, interactions, responsive
   behavior, keyboard and touch behavior when relevant, and accessible labels.
   The starter loading skeleton is temporary infrastructure, not product UI.
   Once the requested first version replaces it, remove `app/_sites-preview`
   and its imports. If nothing else uses `react-loading-skeleton`, remove that
   dependency and refresh the lockfile. Remove the temporary `codex-preview`
   metadata marker, replace the starter title and description with the requested
   site's own values, and update starter icons when appropriate before the final
   build unless the user explicitly asked to work on the starter itself.
4. As soon as implementation is complete, run `npm run build` while the
   retained `npm run dev` process stays alive. Fix actual build failures, then
   rerun it. Run lint separately only if the build omits compilation or the user
   asks.
5. Follow the shared preview rules below.
6. Continue to `sites-hosting`. Avoid an unnecessary polish pass after the
   build succeeds.

## Capability path

### Project setup

- For a new site, use the setup flow in **Start new projects immediately** and
  preserve the bundled vinext structure.
- For an existing site, preserve its package manager, lockfile, scripts,
  architecture, and `.openai/hosting.json`. Install only when dependencies are
  absent. Do not replace a working structure merely to use the starter.
- Keep site code within the selected project surface.

### Shape the product

- Before comprehensive implementation, apply the bounded slice and complete the
  **First meaningful preview** handoff above.
- Build the first viewport around the requested product, not generic dashboard
  chrome.
- For a new site, replace the starter loading skeleton completely and remove
  `app/_sites-preview` and its imports. Remove `react-loading-skeleton` and
  refresh the lockfile if the finished site no longer uses it. Remove the
  temporary `codex-preview` metadata marker, update `app/layout.tsx` with the
  finished site's title and description, and replace any other starter metadata
  before final validation. Preserve the skeleton only when the user explicitly
  asked to work on the starter itself.
- Use concrete, product-specific copy and realistic data.
- Once the site's visual direction, primary headline, and supporting copy are
  stable, freeze a compact social-preview brief and launch exactly one
  `imagegen` request in parallel with the remaining site implementation and
  validation. Ask imagegen to create the complete social card, including its
  typography, as one cohesive landscape image. The card must represent the
  actual finished site by reusing its content, brand palette, typography
  treatment, and distinctive visual motifs; optimize it for visual impact and
  legibility in X, Slack, iMessage, and other link unfurls.
- Inspect the returned image for incorrect, missing, or invented text. Retry
  once only when the card is unusable; do not generate multiple candidates in
  parallel. If validation succeeds, save the image as `public/og.png` and update
  `app/layout.tsx` with site-specific Open Graph and X metadata using an absolute
  URL derived from the incoming request host. Run the final build after wiring
  the asset. Never ship a generic or starter fallback image; if no bespoke card
  passes validation, omit `og:image` instead.
- Use root or layout social metadata only for the root and non-detail routes. For every independently shareable detail route, use `generateMetadata` or the framework's equivalent route-metadata API to override, rather than inherit or copy, the site-wide `title`, `description`, `openGraph.title`, `openGraph.description`, `openGraph.images`, `twitter.title`, `twitter.description`, and `twitter.images` with values derived from the same authoritative record the page renders. Reuse that record's existing primary content image with an absolute URL derived from the incoming request host. When the record has no image, explicitly clear inherited Open Graph and X image metadata so the emitted metadata contains no image; never fall back to `public/og.png`. Do not make per-route `imagegen` requests; keep the single site-wide social-card flow above as the only generated social card.
- When the site has independently shareable detail routes, validate every detail route when there are one or two, or at least two representative detail routes when there are more, before the final build. Confirm that each checked route's emitted page title and description, Open Graph title and description, and X title and description match its visible record instead of the site-wide values, that the site-wide `public/og.png` asset is not referenced, and that any emitted social image matches the record's existing primary image and uses an absolute URL; validating only the root layout metadata is insufficient.
- Avoid speculative features and unnecessary client state.
- Use `sites()` from `@openai/sites-vite-plugin` and produce Cloudflare Worker-compatible ESM output.

### Add only requested capabilities

- For durable state, records, uploads, or other persistence, read
  [Persistence and storage](references/persistence-and-storage.md).
- For any SQLite schema or query work, also read [SQLite](references/sqlite.md).
- For identity-aware or sign-in-gated behavior, read
  [Authentication](references/authentication.md).
- Use browser storage only for device-local preferences or explicitly local
  state.
- Keep logical D1 and R2 declarations in `.openai/hosting.json`; Sites owns the
  real Cloudflare resources and deployment wiring.
- Keep local `.env` and `.env.example` keys aligned. Manage hosted runtime
  values through Sites.

### Validate capability work

- Run the deployment build once after the complete implementation. If a D1
  schema changed, generate and inspect its migration. Fix real failures before
  hosting.

## Preview rules

- In a visible foreground thread, the **First meaningful preview** gate is the
  only local opening point. If the gate has not passed, keep the browser closed;
  never open the skeleton as a fallback. If `open_in_codex` fails after the gate
  passes, report it and continue.
- For an existing site, preserve its normal package and development flow.
- In a delegated, background, or invisible thread, skip `open_in_codex` and say
  why.
- Perform no screenshots, DOM inspection, clicking, resizing, or visual QA
  unless the user explicitly requests browser testing.
- Do not scan ports or repeatedly open the browser.

## Hosting handoff

Use `sites-hosting` after validation. Do not finish with only a local build
unless the user requested local-only work. Return the deployed Sites URL as the
primary deliverable. Do not include file paths, commands, or validation jargon
unless the user asks. Keep the development server running until hosting
finishes, then stop it during final teardown.
