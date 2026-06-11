# Module 2: Market Style Analysis - Execution Guide

## Key Requirements

- **Output:** 3 design strategies (1 market-aligned + 2 exploratory)
- **Reference images:** Strategy 1 may use `reference_image_list` for style direction only
- **Originality:** Extract only abstract principles such as color mood, typography direction, and composition rhythm
- **Distinctiveness:** Output must remain original and clearly differentiated

---

## Execution Steps

### Step 1: Identify the category

Extract industry or usage context from the request.

### Step 2: Collect market visuals

Use `info_search` with `image=true`:

```python
info_search(queries=[
    {"query": "[industry] logo styles 2024", "image": true},
    {"query": "[industry] brand visual trends", "image": true}
])
```

### Step 3: Analyze style patterns

Observe:
- **Colors:** common palettes and contrast patterns
- **Styles:** minimal, geometric, premium, playful, etc.
- **Symbols:** abstract vs literal motifs
- **Typography:** sans-serif, serif, custom lettering

### Step 4: Analyze representative examples

Use `image_analysis` on 2-3 representative images:

```python
image_analysis(tasks=[
    {"image_url": "[url]", "query": "Analyze colors, shapes, style, and typography direction."}
])
```

### Step 5: Formulate 3 strategies

- **Strategy 1:** Market-aligned
- **Strategies 2-3:** Exploratory and differentiated

---

## Output Format

```text
**Market Visual Trends:**
[Industry] visuals commonly show [trend 1], [trend 2].

**Visual Insights:**
- Colors: [patterns]
- Styles: [approaches]
- Typography: [signals]

---

## Market-Aligned Strategy

**Strategy 1: [Title]**
- Approach: [one sentence]
- Brand Value: [why it works]
- Abstract Principle: [style/color/typography principle]
- Differentiation: [how the direction stays original]

---

## Exploratory Strategies

**Strategy 2: [Title]**
- Approach: [fresh direction]
- Brand Value: [differentiation benefit]
- Innovation Angle: [what is different]
- Risk/Reward: [trade-off]

**Strategy 3: [Title]**
- Approach: [fresh direction]
- Brand Value: [differentiation benefit]
- Innovation Angle: [what is different]
- Risk/Reward: [trade-off]
```

---

## Image Generation Rules

- Each logo should be generated in a separate image call.
- Reference images are for style direction only, never for direct copying.
- Always add originality guidance to prompts.
- Prefer category examples over iconic trademarked logos.
