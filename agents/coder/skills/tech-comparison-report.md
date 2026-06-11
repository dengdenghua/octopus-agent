---
name: tech-comparison-report
description: Side-by-side technology comparison report with scoring and a final recommendation, targeting a specific use-case context.
when_to_use: User asks to compare two or more technologies, frameworks, databases, or tools for a specific project type or team context; requests like 'which should I pick', 'compare X vs Y for Z', or 'help me choose between A and B'.
sample_source: internal-2025
learned_at: 2026-04-24T02:41:04
learned_by_model: claude-sonnet-4-6
---

# Output Template

# {option_a} vs {option_b} · {year} {context} 选型报告

## 维度对比

| 维度 | {option_a} | {option_b} |
|------|{col_a_header}|{col_b_header}|
| {dimension_1} | {a_dim1} | {b_dim1} |
| {dimension_2} | {a_dim2} | {b_dim2} |
| {dimension_3} | {a_dim3} | {b_dim3} |
| {dimension_4} | {a_dim4} | {b_dim4} |
| {dimension_5} | {a_dim5} | {b_dim5} |

## 评分

- {option_a}: {score_a}/10 — {score_a_rationale}
- {option_b}: {score_b}/10 — {score_b_rationale}

## 最终选型

**推荐 {winner}** —— {decision_criterion}

## 切换条件

{fallback_condition}

# Style Notes

- Title format: '{OptionA} vs {OptionB} · {year} {context} 选型报告' — always include year and target context in the heading
- Comparison table: exactly 3 columns (维度, OptionA, OptionB); aim for 4–6 dimension rows covering performance, scalability, ops, and use-case-specific concerns
- Scoring scale: X/10 with a short em-dash clause (≤10 Chinese characters) explaining the key differentiator — no long prose
- Final recommendation: single bold sentence naming the winner followed by an em-dash and one concise justification sentence anchored to the stated context
- Fallback/switch condition: one short paragraph describing the concrete scenario where the non-recommended option becomes valid — keeps the report honest and actionable
- Language: match the user's language (Chinese in sample); keep technical terms (e.g. RLS, ACID, JSONB) untranslated as proper nouns
- No citations or external links required; internal knowledge is sufficient
- Keep the entire report short — the sample fits under ~30 lines; avoid padding with background history or generic feature lists
