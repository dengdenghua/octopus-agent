# Module 2: Competitor Analysis - Execution Guide

## Key Requirements

- **Output:** 3 Design Strategies (1 industry-aligned + 2 innovative)
- **Reference images:** Strategy 1 MAY use `reference_image_list` for **style direction only** (NOT for copying specific elements)
- **Originality (CRITICAL):** Extract **abstract principles only** (color palettes, style moods, typography approaches) - NEVER specific shapes, icons, or layouts
- **Anti-Infringement:** Output must be 100% original and legally distinct from all reference logos

---

## Execution Steps

### Step 1: Identify Industry

Extract industry keywords from Module 1 or user query.

### Step 2: Search Competitor Logos

Use `info_search` with `image=true`:

```python
info_search(queries=[
    {"query": "[industry] company logos 2024", "image": true},
    {"query": "[industry] brand logo design trends", "image": true}
])
```

### Step 3: Analyze Visual Trends

Observe:
- **Colors:** Dominant palettes in industry
- **Styles:** Minimalism, 3D, gradients, etc.
- **Icons:** Abstract vs literal, common motifs
- **Typography:** Sans-serif, custom lettering

### Step 4: Analyze Competitor Logos

Use `image_analysis` on 2-3 representative logos:

```python
image_analysis(tasks=[
    {"image_url": "[url]", "query": "Analyze design elements: colors, shapes, style, typography."}
])
```

### Step 5: Formulate 3 Strategies

- **Strategy 1:** Industry-Aligned (may use reference images for **style direction only**, output must be original)
- **Strategies 2-3:** Innovative (no competitor references)

---

## Output Format

```
**Industry Visual Trends:**
[Industry] logos show [trend 1], [trend 2]. Analyzed: [competitors].

**Visual Insights:**
- Colors: [patterns]
- Styles: [approaches]
- Icons: [types]

---

## 🎯 Industry-Aligned Strategy

**Strategy 1: [Title]**
- Approach: [one sentence]
- Brand Value: [why it works]
- Abstract Principle: [style/color/typography insight extracted - NOT specific shapes]
- Original Direction: [how our design will be distinctly different while following the trend]

---

## 💡 Innovative Strategies

**Strategy 2: [Title]**
- Approach: [fresh direction]
- Brand Value: [differentiation benefit]
- Innovation Angle: [what's different]
- Risk/Reward: [trade-off]

**Strategy 3: [Title]**
- Approach: [fresh direction]
- Brand Value: [differentiation benefit]
- Innovation Angle: [what's different]
- Risk/Reward: [trade-off]
```

---

## Example Output

```
**Industry Visual Trends:**
Tech logos favor geometric minimalism, gradient accents, network motifs.

**Visual Insights:**
- Colors: Navy, cyan, purple
- Styles: Flat geometric (60%), gradients (30%)
- Icons: Hexagons, abstract nodes

---

## 🎯 Industry-Aligned Strategy

**Strategy 1: Geometric Network**
- Approach: Abstract lattice symbolizing connectivity
- Brand Value: Conveys scalability and technical trust
- Abstract Principle: Industry favors geometric forms and tech-blue palettes for data services
- Original Direction: Create unique connected node pattern with gradient flow, distinctly different from existing logos

---

## 💡 Innovative Strategies

**Strategy 2: Cultural Fusion**
- Approach: Eastern aesthetic meets tech
- Brand Value: Strong differentiation in geometric-dominated market
- Innovation: Breaks "blue geometric" norm with cultural elements
- Risk/Reward: May seem less "tech" / highly memorable

**Strategy 3: Organic Growth**
- Approach: Natural curves replacing cold geometry
- Brand Value: Warmth in tech-heavy space
- Innovation: Humanizes technology brand
- Risk/Reward: May dilute tech credibility / emotional connection
```

---

## Image Generation Rules

**🚨 CRITICAL: Each logo MUST be a separate image generation call**
- ❌ WRONG: "Generate 2 variations" → merged into one image
- ✅ CORRECT: 2 separate calls → 2 individual images

**Strategy 1 (Industry-Aligned):**
- MAY use `reference_image_list` for **style direction only** (color mood, typography style, overall aesthetic)
- **NEVER use reference images from famous/iconic brands** (e.g., Apple, Nike, Google) - describe abstract principles in text instead
- **ALWAYS include in prompt:** "Original design only, must not resemble any existing brand logos or trademarks"
- Describe the abstract principle (e.g., "geometric minimalism with tech-blue palette") rather than copying specific elements
- Each variation = separate call

**Strategies 2-3 (Innovative):**
- Do NOT use competitor references
- Focus on innovation angle in prompt
- Each variation = separate call

**Anti-Infringement Checklist:**
- ✅ Extracted only abstract principles (style mood, color direction, typography approach)
- ✅ No specific shapes, icons, or layouts copied from references
- ✅ Prompt includes originality guidance
- ✅ Famous brand logos NOT used as direct references

**Total Output:** 3 strategies × 2 variations = **6 separate image generation calls** = 6 individual logo files
