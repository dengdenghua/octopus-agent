# Plugin Author Migration Guide

This guide is the stable handoff for third-party or local plugin authors who
want a plugin to stay compatible with the Octopus operator runtime.

## Compatibility Contract

A plugin should declare the surfaces it exposes and keep those surfaces stable
across releases:

- Skills must include a clear description and any required setup.
- MCP tools must document side effects and expected inputs.
- App surfaces must name the operator workflow they support.
- Lifecycle hooks must be auditable and testable.

The smoke summary in `/api/plugins/smoke-summary` is the first compatibility
gate. A plugin can be usable with a `review_required` verdict, but it must not be
silently treated as production-ready.

## Migration Steps

When migrating a plugin between releases:

1. Run local smoke checks before enabling the plugin for operators.
2. Resolve missing capability, malformed manifest, and stale hook warnings.
3. Review inferred permissions and convert them into explicit permissions when
   possible.
4. Add or update regression tests for the operator workflow the plugin enables.
5. Record unresolved compatibility warnings as accepted risk before release.

## Permission Review

Permission review is mandatory for plugins that execute tools, invoke MCP
servers, read or write local files, or register lifecycle hooks.

The review should answer:

- Which permission is required?
- Which operator action triggers it?
- Can the permission be narrowed?
- Is there replay or audit evidence for the workflow?

If a plugin has inferred permissions, treat them as review-required until a
human accepts the risk or the manifest is updated.

## Release Checklist

Before release, confirm:

- Compatibility smoke checks pass or show explicit review-required rows.
- Permission review status is visible to the operator.
- Migration notes describe breaking changes and required operator action.
- Hook behavior is covered by regression tests.
- The plugin can be disabled without corrupting memory, replay, or governance
  audit records.
