---
name: harness-findings-report
description: Multi-file generated report pattern that keeps findings.json as the source, chart.canvas.tsx as the chart module, and report.canvas.tsx as a thin shell.
category: engineering
---

Use this when generating a Canvas report from scored findings, harness-readiness
analysis, AI delivery evidence, or another report where findings must stay
machine-readable.

Required files:
1. `findings.json`
   - Top-level keys: `summary` and `findings`.
   - Put `modelId`, headline scores, score rows, suggestions, and method notes
     under `summary`.
   - Every visible score row must include `findingRefs` that point to
     `findings[].id`.
   - Every finding row should include evidence, risk, recommendation, pass check,
     and row-scoped AI action prompt fields.

2. `chart.canvas.tsx`
   - Import visual primitives from `qoder/canvas`.
   - Export one default chart component, for example `ReportChart`.
   - Receive report data as props. Do not import `findings.json` unless the
     chart is the entry Canvas.
   - Render a chart-capable first view, such as `BarChart`, `RadarChart`,
     `Fluency`, `MaturityMatrix`, or a fallback `Progress` stack.
   - Do not define another summary object or duplicate finding rows.

3. `report.canvas.tsx`
   - Import `reportData` from `./findings.json`.
   - Import `ReportChart` from `./chart.canvas.tsx`.
   - Render `<ReportChart report={reportData} />`.
   - Render finding tables, suggestions, notes, and row-scoped
     `SendToChatButton` actions from `reportData`.
   - Do not create `report.canvas.data.json`, use runtime state, or inline a
     second report object.

Recommended reader order:
1. Agent Fluency or selected chart frame
2. Findings And AI Actions
3. Suggestions
4. Dimension And Method Notes

Minimal shell shape:

```tsx
import { H1, H2, SendToChatButton, Stack, Table } from "qoder/canvas";
import reportData from "./findings.json";
import ReportChart from "./chart.canvas.tsx";

export default function ReportCanvas() {
  return (
    <Stack gap={16}>
      <H1>{reportData.summary.projectName}</H1>

      <H2>Agent Fluency</H2>
      <ReportChart report={reportData} />

      <H2>Findings And AI Actions</H2>
      <Table
        rowKey="id"
        rows={reportData.findings}
        columns={[
          { key: "id", title: "ID" },
          { key: "title", title: "Finding" },
          {
            key: "action",
            title: "AI action",
            render: (row) => (
              <SendToChatButton text={row.aiFixPrompt} options={{ submit: false }}>
                {row.aiFixLabel}
              </SendToChatButton>
            ),
          },
        ]}
      />
    </Stack>
  );
}
```

Validation:
- Run the host Canvas TypeScript check when available.
- Local fallback in this repository:
  `node --test test/canvas-fixture-types.test.mjs`
- Browser preview fallback:
  `npm run build && npx playwright test test/hyperdrive-findings-report.spec.ts`
