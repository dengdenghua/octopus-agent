# 国际化与一致性走查 Spec

## Why
前序走查（侧栏、消息区、文件查看、Agent 团队、浏览器/桌面自动化、渠道连接、次级工作台）已陆续发现约 145 处 `text-[9px]/text-[10px]/text-[11px]/text-[13px]` 非标准字号、若干全英文/全中文硬编码文案（如 `deep-research-panel.tsx` 全英文、`desktop-organizer/page.tsx` 全中文硬编码），以及零散的硬编码色值与原生控件。这些不一致破坏了扁平极简设计的统一感，并让 i18n key 类型系统失去意义。本 spec 用于一次性收口国际化与一致性残留。

## What Changes
- **统一字号**：将 `text-[9px]/text-[10px]/text-[11px]` 统一为 `text-xs`（12px），`text-[13px]` 统一为 `text-sm`（14px），`text-[14px]/text-[15px]` 分别统一为 `text-sm`/`text-base`。
- **硬编码文案 i18n 化**：`deep-research-panel.tsx`（全英文）与 `desktop-organizer/page.tsx`（全中文）的所有面向用户字符串抽取到 i18n 类型系统，新增对应 key 并同步 zh-CN/en-US/ja-JP/ko-KR 四份 locale 文件。
- **硬编码颜色语义化**：在已修改的 9 个次级工作台文件中，把残留的 `text-red-500/text-green-500/text-blue-500` 等改为 `text-destructive/text-emerald-500/text-primary` 等语义 token（status 色：red→destructive，green→emerald-500/primary，blue→primary）。
- **原生控件替换**：在 9 个文件内将原生 `<input>/<button>/<select>`（非 a11y 必要保留）替换为 shadcn `Input`/`Button`/`<Select>`（仅在已有同类型 shadcn 组件被使用的文件中替换，避免引入风格差异）。
- **i18n key 一致性回归**：扫描全部 4 份 locale 文件，确保所有 key 与 `types.ts` 严格对齐（无遗漏、无多余、无类型不匹配）。

## Impact
- Affected specs: 次级工作台走查（已提交 commit `283ce75cc`）、Agent 团队走查（commit `3862628c8`）、渠道/外部连接走查（commit `3331e1776`）
- Affected code:
  - `frontend/src/components/workspace/deep-research-panel.tsx`（全英文硬编码抽取）
  - `frontend/src/app/workspace/desktop-organizer/page.tsx`（全中文硬编码抽取）
  - `frontend/src/core/i18n/locales/{types,zh-CN,en-US,ja-JP,ko-KR}.ts`（新增 key + 一致性回归）
  - 9 个次级工作台文件内的字号/颜色/控件统一（约 30 处）
  - 其余同目录文件中约 145 处 `text-[Npx]` 字号统一

## ADDED Requirements

### Requirement: 字号统一为 Tailwind 标准
系统 SHALL 在所有非测试 `.tsx` 文件中使用 Tailwind 标准字号 token（`text-xs/text-sm/text-base/text-lg/text-xl/text-2xl`），禁止使用 `text-[9px]/text-[10px]/text-[11px]/text-[13px]/text-[14px]/text-[15px]` 等任意像素值字号。

#### Scenario: 字号统一
- **WHEN** 开发者扫描代码库中的非标准字号
- **THEN** 所有 `text-[Npx]` 实例已被替换为最接近的 Tailwind 标准字号（≤11px→text-xs，13-14px→text-sm，15px→text-base）

### Requirement: 面向用户文案全部 i18n 化
系统 SHALL 将所有面向用户的字符串通过 typed i18n key（`t.xxx.yyy`）输出，禁止在 `.tsx` 中硬编码英文或中文字符串字面量（注释、console、debug 数据除外）。

#### Scenario: 硬编码文案抽取
- **WHEN** 用户在 `deep-research-panel.tsx` 或 `desktop-organizer/page.tsx` 中浏览 UI
- **THEN** 所有可见文案来自 `useI18n()` 的 `t.*` 字段，且 `types.ts` 与 4 份 locale 文件均包含对应 key 与翻译

### Requirement: 颜色使用语义 token
系统 SHALL 在 9 个次级工作台文件中使用语义设计 token（`--destructive/--primary/--foreground/--muted-foreground` 等），禁止直接使用 `text-red-500/bg-red-500/text-blue-500` 等硬编码 Tailwind 调色板色（status badge 中 emerald/amber/blue 状态色除外，但需保持一致性）。

#### Scenario: 颜色语义化
- **WHEN** 开发者检查 9 个次级工作台文件的 className
- **THEN** 危险/错误色统一为 `text-destructive/bg-destructive/10`，主色为 `text-primary/bg-primary/10`，不再出现裸 `text-red-500` 等

### Requirement: i18n key 类型与 locale 严格对齐
系统 SHALL 保证 `types.ts` 中声明的每个 i18n key 在 zh-CN/en-US/ja-JP/ko-KR 四份 locale 文件中均有对应实现，且类型签名一致（函数式 key 的参数与返回类型一致）。

#### Scenario: i18n 一致性
- **WHEN** 运行 `pnpm tsc --noEmit`
- **THEN** 编译通过，无 i18n key 缺失或类型不匹配错误

## MODIFIED Requirements

### Requirement: 原生控件使用 shadcn 组件（沿用 project_memory 硬约束）
在 9 个次级工作台文件中，所有 `<input>/<button>/<select>` 控件 SHALL 优先使用 shadcn `Input/Button/Select` 组件；仅当 a11y 要求保留原生属性（如 `aria-label` 自定义、`autoFocus` 等）且 shadcn 组件无法表达时，才保留原生标签但必须补充 `type/aria-label/focus-visible` 三件套。

## REMOVED Requirements
（无）
