# 清理未使用依赖 Spec

## Why

深度评价扫描发现 `tokenlens`、`dompurify`、`@types/dompurify` 三个依赖在 `frontend/src/` 中零引用，且 `streamdown` 也不依赖 `dompurify`。移除可减少 node_modules 体积和 lockfile 复杂度。

## What Changes

- 从 `frontend/package.json` 的 dependencies 移除 `dompurify`
- 从 `frontend/package.json` 的 devDependencies 移除 `@types/dompurify` 和 `tokenlens`
- 运行 `pnpm install` 更新 lockfile

## Impact

- Affected code: `frontend/package.json`、`frontend/pnpm-lock.yaml`

## ADDED Requirements

### Requirement: 无未使用依赖

`frontend/package.json` SHALL 不包含 `tokenlens`、`dompurify`、`@types/dompurify`。

#### Scenario: 移除后验证
- **WHEN** grep `from ["']tokenlens` 在 `frontend/src/`
- **THEN** 0 命中（移除前已 0 命中）
- **WHEN** `pnpm typecheck`
- **THEN** 退出码 0
