# Logo Design Prompt Guide

Specialized guide for constructing high-quality logo generation prompts using the Accio Workflow.

---

## 🚨 CRITICAL EXECUTION PRINCIPLE 🚨

**When generating design assets (Primary Logo + Mockup/Specs/Variations/Custom Assets):**

✅ **CORRECT:** Generate Primary Logo FIRST → Wait for completion → Use its URL as `reference_image` for ALL other assets

❌ **WRONG:** Generate all assets simultaneously in one batch

**Why:** Design coherence requires all derivative assets to reference the same primary logo. Parallel generation creates inconsistent, disconnected designs that cannot be used together.

**Applies to:**
- Standard assets: Design Specs Board, Brand Application Mockup, Logo Variations
- Custom user requests: Social media assets, packaging, stationery, signage, product mockups, etc.

**Reference locations:** Section 2 Case B, Section 6B (Design Assets Templates), Module 3 execution.

---

## 1. Logo Foundation (Core Dimensions)

Before generating a prompt, define these two core dimensions to ensure alignment with brand identity.

### **A. Logo Type Selection**

| Type | Description | Best For |
| :--- | :--- | :--- |
| **Graphic Logo (Default)** | Contains a distinct icon or symbol paired with text. | Building brand IP, symbolic storytelling, memorable visual identity. |
| **Text Logo (Wordmark)** | Focuses purely on custom typography without icon. | Minimalism, strong brand names, Scandinavian aesthetic, short names. |

**Default:** If not specified, always use **Graphic Logo**.

---

### **B. Style Selection Matrix**

| Style Name | Key Characteristics | Best For |
| :--- | :--- | :--- |
| **3D Luxury/Fashion (Default)** | Couture aesthetics, 3D depth (6-10mm), polished metallic textures, refined contours, premium 3-layer lighting. | High-end Fashion, Luxury Branding, Jewelry, Watches, Premium Lifestyle. |
| **Cartoon/Mascot** | Playful characters integrated with typography, flat vector, vibrant solid colors. | F&B, Gaming, Kids' brands, Mobile Apps, IP development. |
| **Minimalist Flat** | Geometric simplicity, heavy use of negative space, clean lines, maximum legibility. | Tech Startups, Corporate, Architecture, Modern Design. |
| **Vintage/Retro** | Badge/Emblem layouts, ornate borders, textured backgrounds, heritage color palettes. | Breweries, Coffee, Handcrafted goods, Traditional trades. |
| **Tech/Futuristic** | Sleek geometry, neon/cyan accents, circuit-inspired motifs, dark "cyber" aesthetic. | AI, Software, Hardware, Cyber-security, Space-tech. |

**Default:** If not specified, always use **3D Luxury**.

---

## 2. Execution Logic & Defaults

### **Default Behavior Rules:**

1.  **Logo Type Default:** If the user does not specify, always prioritize **Graphic Logo**.
2.  **Style Default:** If the user does not specify, always prioritize **3D Luxury**.
3.  **Quantity Logic:**
    -   **Case A: No Quantity Specified (Default)** → **Generate 3 distinct style themes = 3 logos**. Use batch generation when possible (single call for all 3 logos). See Module 2 for details.
    -   **Case B: Quantity Specified** → Generate the requested number of logos, distributing across different styles when appropriate.
    -   **Case C: Design Assets Requested** → **🚨 SEQUENTIAL generation with reference_image:**
        1.  **Primary Logo(s)** - Generate first (batch if multiple), NO reference_image
        2.  **Design Assets** (specs, mockups, variations, custom assets) - Use primary logo as reference_image
        
        **🚨 CRITICAL - Only execute Case C when user explicitly requests design assets (mockups, specs, variations, packaging, etc.)**
        - **STEP 1:** Generate Primary Logo(s) FIRST, wait for completion
        - **STEP 2:** Use Step 1's output URL as `reference_image` for requested assets
        - **Default Behavior:** If user does NOT mention assets, only generate primary logos (Case A or B)

### **Anti-Infringement Guidelines (CRITICAL)**

#### **A. Request-Level Detection (MUST Check First)**

Before proceeding with any logo generation, detect and handle requests that contain explicit infringement risks.

**Detection Criteria:**
- User explicitly requests to "copy", "clone", "replicate", "imitate", or "use as template" a specific brand's logo
- User requests to take another brand's logo and only replace text/letters/name
- User references a specific trademarked logo and requests minimal modification or direct reproduction

**Response Protocol:**

When infringement risk is detected, you **MUST**:

1. **Acknowledge the limitation clearly** - Explain that directly copying or closely imitating existing brand logos carries legal/trademark risks and cannot be executed as requested
2. **Offer style-based alternative** - Propose to reference the mentioned brand's abstract design principles (color philosophy, typography approach, visual rhythm, geometric style) while creating a **100% original** design
3. **Proceed with original generation** - Generate logos that are inspired by abstract stylistic elements but distinctly original in all specific visual elements

**Key Principle:** Extract and apply **design principles only** (e.g., "bold geometric shapes", "playful primary color palette", "rounded sans-serif typography", "modular block aesthetic") rather than replicating any specific shapes, icons, letterforms, or layouts from the referenced brand.

**Communication Approach:**
- Be direct but constructive - clearly state what cannot be done and immediately offer what CAN be done
- Frame the alternative positively - style-inspired original designs can achieve similar visual impact without legal risk
- Proceed to generation after explaining - do not wait for user re-confirmation unless they request changes

#### **B. Prompt-Level Protection (During Generation)**

When constructing image generation prompts:
- **NEVER copy or closely imitate** specific shapes, icons, or layouts from known brand logos
- Extract **abstract design principles only** (e.g., "geometric minimalism", "warm color palette") - NOT specific visual elements
- **ALWAYS include in image prompts:** "Original design, must not resemble any existing brand logos"
- Reference images are for **style direction only** - the output must be distinctly original
- If a reference logo is too iconic/famous, describe the abstract principle instead of using the image
- Ensure all outputs are **commercially safe and legally distinct** from existing trademarks

---

## 3. Complete Logo Generation Workflow

This section defines the complete user-facing workflow with dynamic modules based on user context.

### **Workflow Structure & Default Execution**

```
┌─────────────────────────────────────────────────────────────┐
│                    Logo Generation Flow                     │
├─────────────────────────────────────────────────────────────┤
│  0. Anti-Infringement Check (MANDATORY - See Section 2)     │
│  ─────────────────────────────────────────────────────────  │
│  1. Brand/Industry Understanding (Recommended)              │
│  2. Design Solutions (Required)                             │
│  3. Next Steps Guidance (Recommended)                       │
└─────────────────────────────────────────────────────────────┘
```

**⚠️ Step 0 - Anti-Infringement Check:** Before starting any module, apply Section 2 "Anti-Infringement Guidelines Part A" to detect explicit copy/clone requests. If detected, respond with explanation and proceed with style-inspired original design approach.

**Default Execution Strategy:**

⚠️ **DEFAULT = Execute Streamlined Workflow (Modules 1+2+3)**

**Execution Rules:**

1. **Full Workflow (1+2+3)** - DEFAULT, execute when:
   - User provides brand name + industry/purpose (most common case)
   - User query is generic/vague (needs brand context)
   - No explicit "skip analysis" instruction

2. **Quick Generation (Module 2 only)** - Execute ONLY when:
   - User explicitly says: "skip analysis", "just the logo", "no research needed"

**Example Decision Tree:**

| User Query | Execute Modules | Reason |
|---|---|---|
| "Logo for Accio, e-commerce agent, hand-drawn style" | **1+2+3** (Full) | ✅ Has brand + industry → **Default workflow** |
| "Coffee shop logo" | **1+2+3** (Full) | ✅ Generic query → **Default workflow** |
| "Tech startup logo, modern minimalist" | **1+2+3** (Full) | ✅ Style mentioned → **Default workflow** |
| "Just generate logo, skip the analysis" | **2** Only | ⚠️ User explicitly opted out → Quick generation |

---

### **Module 1: Brand/Industry Understanding (Recommended)**

#### **Objective**
Avoid "beautiful but irrelevant" designs by ensuring outputs align with brand context.

#### **Trigger Logic**
- **Default:** Always output UNLESS user explicitly says "just the image, no analysis"
- **Skip if:** User says "skip analysis", "just logo", "no explanation needed"

#### **Execution Logic**

**⚠️ CRITICAL: This module CANNOT be executed without reading the execution guide first.**

**Step 1: Read the execution guide (MANDATORY):**

```
read("./brand-understanding-execution.md")
```

**Step 2: Execute ALL steps in the guide (MANDATORY):**
- ✅ Step 1: Research Brand Information (use `info_search`)
- ✅ Step 2: Extract/Infer Context from Research + User Query
- ✅ Step 3: Analyze Existing Logo (if provided, use `image_analysis`)
- ✅ Step 4: Synthesize Insights (output in specified format)

The guide contains detailed instructions, output format templates, and tool usage examples that MUST be followed.

---

### **Module 2: Design Solutions (Required)**

#### **Objective**
Deliver professional, commercial-ready, multi-option visual solutions based on brand understanding and design strategy.

#### **Execution Logic**

**A. Quantity Logic:**

1. **Default Behavior (User does NOT specify quantity):**
   - Generate **3 distinct style themes** (NO variations per theme)
   - **3 total logos** with clear visual differentiation
   - Select styles based on brand context from Module 1:
     - Consider industry characteristics
     - Balance between classic/safe and creative/innovative approaches
     - Ensure each style offers unique visual identity

2. **User specifies quantity:**
   - Generate the requested number of logos
   - Distribute across different style approaches when appropriate

**B. Logo Generation Strategy:**

✅ **RECOMMENDED: Batch generation when possible**

**For standard multi-style requests (default 3 logos):**
- Generate all logos in a **single batch call** when they share common parameters (size, format, quality)
- Use array/list format in prompt to specify multiple design variations
- This improves efficiency and maintains consistent technical quality across outputs

**When to use separate calls:**
- User explicitly requests sequential review between designs
- Designs require fundamentally different technical parameters (size, aspect ratio, format)
- Designs have complex dependencies (e.g., derivative assets referencing primary logo)

**Total Output:** For a standard request, generate **3 logos in one batch** resulting in 3 distinct downloadable files.

---

**C. Sequential Generation (Only when user requests design assets):**

⚠️ **Trigger Conditions:** Execute sequential generation ONLY when user explicitly requests:
- Design specifications/specs board
- Brand application mockups
- Logo variations on different backgrounds
- Custom assets (packaging, social media, stationery, etc.)

**Sequential Process:**
- **STEP 1:** Generate Primary Logo FIRST (no reference_image)
- **STEP 2+:** WAIT for Step 1 completion, THEN generate requested assets using Step 1 URL as reference_image

**Default Behavior:** If user does NOT mention additional assets, only generate the primary logos (3 logos in batch).

---

1. **Combine Elements:**
   - Brand Understanding (from Module 1)
   - Professional Template (from Section 5: Style-Specific Templates)
   
2. **Technical Constraints:**
   - **Strictly honor user requirements:** Color, size, style, specific elements
   - **Output format:** PNG with solid color background (pure white #FFFFFF or user-specified color)
   - **⚠️ Background-Logo Contrast (CRITICAL):** Background color MUST contrast with logo colors
     - If logo uses light colors (white, pink, pastels) → Use dark background (#2C2C2C, #000000)
     - If logo uses dark colors (black, navy, dark gray) → Use light background (#FFFFFF, #F5F5F5)
     - If logo has mixed light/dark elements → Choose background that shows ALL elements clearly
   - **Clean edges:** No stray pixels, shadows, or dirty borders
   - **Download-ready:** User can directly use without post-processing (easy for background removal/replacement if needed)

3. **Reference Image Usage:**
   - If user uploaded existing logo/brand materials, include in `reference_image_list` to maintain visual consistency
   - Avoid using external reference images unless user explicitly provides them
   - Always ensure outputs are original and legally distinct

**D. Custom Assets & Mockup Rendering (Conditional):**

**Trigger:**
- User explicitly mentions specific products/use cases/additional deliverables
- Examples: 
  - "dishwashing liquid logo...Design front and back labels"
  - "Show it on social media"
  - "Need business card and letterhead designs"
  - "Apply to coffee cup and tote bag"

**Execution:**
- Generate primary logos first (batch generation)
- **THEN** select 1 recommended solution from the generated logos
- Generate custom mockup/asset using selected logo's URL as `reference_image`
- **Ensure consistency:** Same proportions, colors, and alignment across all mockup elements

⚠️ **Important:** Do NOT automatically generate mockups/assets unless user explicitly requests them.

#### **Output Content**

**Output Structure:**

Total Output: **3 distinct style themes = 3 logos**

**⚠️ IMPORTANT: Keep output concise. Use the simplified format below.**

For each logo, output:

```
**[Style Theme Title]**

[Logo Image]

[One paragraph combining: Design description (colors, shapes, typography) + Design value (brand message, image positioning)]
```

**Example:**

```
**Style 1: Geometric Precision**

[PNG Logo 1]

Abstract network motif with gradient flow from Navy #1A2B4A to Cyan #00D4FF, using Montserrat Bold typography. The geometric simplicity conveys digital trust and scalability, suitable for both B2B and B2C contexts while maintaining high recognizability from favicon to billboard sizes.

---

**Style 2: Cultural Fusion**

[PNG Logo 2]

Ink Blue #2C3E50 with Cloud White #F8F9FA, integrating cultural elements that break from typical tech aesthetics. Creates instant memorability and strong storytelling potential, with high differentiation in crowded markets while maintaining cultural resonance with target regions.

---

**Style 3: Organic Flow**

[PNG Logo 3]

Warm earth tones with natural curves replacing cold geometry. Humanizes the technology brand through soft, approachable forms while maintaining professional credibility, ideal for brands seeking emotional connection with users.
```

**Anti-Infringement Guidance (MANDATORY):**

⚠️ **Before generating, ensure Section 2 "Anti-Infringement Guidelines Part A" (Request-Level Detection) has been applied.** If user requested to copy/clone a specific brand logo, respond with explanation and proceed with style-inspired original design only.

When constructing image generation prompts:
- **ALWAYS include:** "Original design only, must not resemble any existing brand logos or trademarks"
- **Extract abstract principles ONLY:** color palette directions (e.g., "warm earth tones"), style approaches (e.g., "geometric minimalism"), typography moods (e.g., "modern sans-serif") - NEVER specific shapes, icons, or layouts
- **NEVER reference famous brand names** in prompts (e.g., don't say "like [Brand]'s logo" or "[Brand]-inspired")
- **NEVER use trademarked logos as reference_image** for direct replication - only for abstract style direction
- **Verify originality:** If generated design appears similar to a known brand, regenerate with more explicit differentiation guidance
- Ensure all outputs are **commercially safe and legally distinct** from existing trademarks

---

### **Module 3: Next Steps Guidance (Recommended)**

#### **Objective**
Proactively guide users toward natural next actions based on their context and results.

#### **Trigger Logic (Simplified)**

**Execute (Default):** Always provide next steps UNLESS user explicitly says "don't suggest anything else"

This module should always run as it helps users understand their options and encourages iteration.

#### **Execution Logic**

**⚠️ CRITICAL: This module CANNOT be executed without reading the execution guide first.**

**Step 1: Read the execution guide (MANDATORY):**

```
read("./next-steps-execution.md")
```

**Step 2: Follow the contextual guidance (MANDATORY):**
- Identify which situation applies (multiple solutions / product type / minimal info / user selected)
- Provide 2-3 relevant next steps based on the situation
- Use the output format templates and examples from the guide

The guide contains different situation templates with specific, actionable next step suggestions that MUST be followed.

---

## 4. Accio Design Workflow (3-Step Process)

Follow this workflow to generate high-quality logo prompts with creative depth.

### **Step 1: Information Gathering**

Collect these 4 core elements (can be extracted from user query or asked directly):
- **Industry** (e.g., Tech, Fashion, F&B)
- **Core Feature/Philosophy** (e.g., "Speed and Innovation", "Organic Growth")
- **Logo Type** (Graphic/Text)
- **Style Preference** (Select from Style Matrix)

---

### **Step 2: Accio Concept Generation (Creative Logic)**

Derive a **creative concept** that bridges brand philosophy and visual output.

**Concept Formula:**
`[How the brand element is reimagined] + [What it symbolizes] + [Visual/typographic approach]`

---

### **Step 3: Prompt Construction**

Combine the **Accio Concept** with **Technical Standards** (Materials, Lighting, Composition) from the templates below.

---

## 5. Comprehensive Design Style Library

### **Overview**

A unified library of **9 professional design styles** stored in `design_prompt_library.csv`, each containing:
- **Design Principles**: Technical specifications (Form, Structure, Strokes, Color, Effects, Typography)
- **Complete Template**: Ready-to-use prompt template with `[BRAND NAME]` placeholder
- **Usage Scenarios**: When each style is most appropriate

### **Library Structure**

| # | Style | Best For | Has Template |
|:---|:---|:---|:---:|
| 1 | Modern Minimal | Tech Startups, Corporate, Architecture | ✅ |
| 2 | Abstract Geometric / Typographic Experiment | Editorial, Design Studios, Avant-garde | ✅ |
| 3 | Retro American / 80s Film Mark | Entertainment, Media, Vintage-inspired | ✅ |
| 4 | Hand-Drawn Vintage (Modern-Restraint) | Breweries, Coffee, Traditional Trades | ✅ |
| 5 | Fashion / Beauty (Light Luxury) | High-end Fashion, Cosmetics, Jewelry | ✅ |
| 6 | Modern Tech / Futuristic Tech | AI, Software, Data Services, Cyber-security | ✅ |
| 7 | Cute Cartoon but Premium (Not Childish) | F&B, Gaming, Kids' brands (mature execution) | ✅ |
| 8 | Solid Bold Geometric (Unified) | Sports, Energy, Bold Consumer Brands | ✅ |
| 9 | 3D Luxury (Premium Fashion) | Couture, Luxury Branding, Premium Lifestyle | ✅ |

### **How to Access the Library**

⚠️ **CRITICAL:** Always read **complete row data** (all fields: Number, Style, When_To_Use, Prompt_Principles, Template), not just Template field.

**Recommended Approach: Read Complete Style Information**

```bash
# Read complete information for specific styles (e.g., rows 0, 4, 8)
python3 -c "import csv; f=open('[/path/to]/design_prompt_library.csv', encoding='utf-8'); reader=list(csv.DictReader(f)); styles=[0, 4, 8]; print('\\n\\n'.join([f\"{reader[s]['Number']}. {reader[s]['Style']}\\nWhen: {reader[s]['When_To_Use']}\\nPrinciples: {reader[s]['Prompt_Principles']}\\nTemplate: {reader[s]['Template']}\" for s in styles])); f.close()"
```

**Alternative: List All Styles (Overview)**

```bash
# List all available styles with usage scenarios
python3 -c "import csv; f=open('[/path/to]/design_prompt_library.csv', encoding='utf-8'); reader=list(csv.DictReader(f)); print('\\n'.join([f\"{r['Number']}. {r['Style']} → {r['When_To_Use']}\" for r in reader])); f.close()"
```

**Alternative: Search by Keyword**

```bash
# Search for "Tech" related styles and show complete info
python3 -c "import csv; f=open('[/path/to]/design_prompt_library.csv', encoding='utf-8'); reader=list(csv.DictReader(f)); results=[r for r in reader if 'Tech' in r['Style'] or 'Tech' in r['When_To_Use']]; print('\\n\\n'.join([f\"{r['Number']}. {r['Style']}\\nWhen: {r['When_To_Use']}\\nPrinciples: {r['Prompt_Principles']}\\nTemplate: {r['Template']}\" for r in results])); f.close()"
```

### **How to Use This Library**

⚠️ **CRITICAL:** Templates are **reference frameworks only**, NOT ready-to-use prompts.

**Correct Usage Pattern:**

1. **Read Complete Style Data** (all fields: Number, Style, When_To_Use, Prompt_Principles, Template)
2. **Use Prompt_Principles as Technical Guide** - Form, Structure, Strokes, Color, Effects, Typography rules
3. **Use Template as Structure Reference** - Overall prompt organization and format
4. **Build Final Prompt by Integrating Context:**
   - ✅ Brand context from Module 1 (industry, values, target audience, brand personality)
   - ✅ Design insights from Module 2 (competitor visual trends, differentiation strategies, reference images)
   - ✅ User-specific requirements (colors, specific elements, layout preferences, size constraints)
   - ✅ Prompt_Principles technical specifications

**❌ Wrong Approach:**
```
Simply replace [BRAND NAME] in Template and use directly
→ Results in generic, context-free logos
```

**✅ Correct Approach:**
```
Read full style data → Extract Prompt_Principles → Use as technical guide → 
Construct detailed prompt using Module 1+2 insights + User requirements + Principles
→ Results in contextual, brand-aligned logos with professional technical quality
```

### **Integration with Workflow**

```
Module 1 (Brand Understanding)
    ↓
Select 3 appropriate styles from Library (Section 5)
    ↓
Load Templates and replace [BRAND NAME] placeholder
    ↓
Overlay brand-specific insights
    ↓
Generate final prompts for Module 2 (Design Solutions)
```

### **Template Customization Guide**

All templates use `[BRAND NAME]` as placeholder. When customizing:

1. **Replace Brand Name**: `[BRAND NAME]` → Actual brand name
2. **Add Brand Context**: Insert insights from Module 1
3. **Apply User Constraints**: Honor specified colors, shapes, layouts
4. **Ensure Originality**: Guide toward original designs when needed
5. **Batch Generation**: For multi-style requests, use array/list format to generate multiple logos efficiently in one call.

---

## 6. Visual Component Standards

### **Metal Materials (3D Luxury Only)**
- **Polished Champagne Gold:** Warm, high-fashion glow, ideal for feminine luxury.
- **Mirror-Finished Silver:** Precision and modern edge, ideal for avant-garde couture.
- **Satin Rose Gold:** Romantic, soft-touch premium feel for cosmetics and high-end jewelry.
- **Liquid Gunmetal:** Powerful, sleek, and high-tech masculine luxury.
- **Brushed Titanium:** Industrial yet refined, perfect for modern accessory brands.

### **Lighting System (3D Luxury Only)**
- **Key Light:** Soft from upper-left 45°, primary highlights.
- **Rim Light:** Delicate from right side for edge separation.
- **Drop Shadow:** Subtle (10-15% opacity) to anchor in space.

### **Background Standards**
⚠️ **Default:** Use **solid color backgrounds** (no gradients, no textures) for easy background removal/replacement.

⚠️ **CRITICAL - Contrast Rule:** Background color MUST provide high contrast with logo colors to ensure visibility.

**Background Selection by Style:**

| Style | Default Background | Alternative (for contrast) | Selection Rule |
|:---|:---|:---|:---|
| **3D Luxury** | Pure dark gray (#2C2C2C) | Pure white (#FFFFFF) | Use dark if logo is light-colored (rose gold, silver, light pink); use white if logo is dark |
| **Cartoon/Flat** | Pure white (#FFFFFF) | Pure black (#000000) | Use white for colorful/bright logos; use black for pastel/light logos |
| **Tech Futuristic** | Pure black (#000000) | Pure white (#FFFFFF) | Match cyberpunk aesthetic: dark bg for neon colors, white bg for dark schemes |
| **Vintage** | Pure cream (#F5F5DC) | Pure dark brown (#3E2723) | Use cream for dark vintage elements; use dark brown for light/faded designs |

**Contrast Check Examples:**
- ✅ Good: White logo text + Dark gray background (#2C2C2C)
- ✅ Good: Navy logo (#1A2B4A) + White background (#FFFFFF)
- ✅ Good: Light pink logo (#FFD1DC) + Black background (#000000)
- ❌ Bad: White logo + White background (invisible)
- ❌ Bad: Black logo + Black background (invisible)
- ❌ Bad: Light pink logo + Cream background (poor contrast)

**Rationale:** Solid color backgrounds with high contrast enable:
1. Clean background removal for various use cases (print, web, merchandise)
2. Clear logo visibility across all viewing conditions
3. Professional presentation without color conflicts

---

## 6B. Design Assets Templates (Sequential Generation)

🚨 **CRITICAL - SEQUENTIAL EXECUTION REQUIRED** 🚨

**Context:** When user explicitly requests design assets (specs, mockups, variations, packaging, etc.) in addition to primary logo.

**⚠️ IMPORTANT:** This section applies ONLY when user explicitly requests additional design assets. If user only asks for "a logo" or "logo design" without mentioning specs/mockups/applications, skip this section and only generate primary logos.

**Execution Rule:**
1. Generate **Primary Logo(s)** FIRST (can batch if multiple styles)
2. **WAIT** for completion and get image URL(s)
3. **THEN** generate requested design assets using primary logo URL as `reference_image`

**Rationale:** Design coherence requires all derivative assets to reference the same primary logo.

**Execution Example:**
```
User Request: "Logo for my coffee shop, show it on a cup and packaging"

✅ CORRECT FLOW:
Step 1: Generate Primary Logo → Get URL: https://example.com/logo.png
Step 2: Generate Coffee Cup Mockup (reference_image: logo.png)
Step 3: Generate Packaging Mockup (reference_image: logo.png)

User Request: "Design a logo for my tech startup" (NO asset mention)

✅ CORRECT FLOW:
Step 1: Generate 3 logos in batch → Done (no additional assets)
```

---

### **Asset 1: Primary Logo** ⭐ **GENERATE FIRST**
**Execution:** Generate using templates from Section 5 (Comprehensive Design Style Library).
**reference_image:** ❌ **NO** - this is the source image for all subsequent assets.
**Wait for:** ✅ **Completion required** - must get output URL before proceeding to Asset 2-4.

---

### **Asset 2: Design Specs Board** 📐 **OPTIONAL**
**Trigger:** User explicitly requests "design specs", "specifications", "sizing guide"
**Execution:** Generate AFTER Asset 1 completes.
**reference_image:** ✅ **REQUIRED** - Use Asset 1's output image URL.

**Prompt Template:**
```
Transform this logo into a professional design specification board. Keep the original logo centered. Add clean white background with grid. Overlay technical annotations for spacing, sizing (mm/px), and color codes (HEX/RGB). Technical blueprint aesthetic with gray guidelines.
```

---

### **Asset 3: Brand Application Mockup** 🎨 **OPTIONAL**
**Trigger:** User explicitly requests "mockup", "show on products", "real-world application"
**Execution:** Generate AFTER Asset 1 completes.
**reference_image:** ✅ **REQUIRED** - Use Asset 1's output image URL.

**Prompt Template:**
```
Apply this logo to realistic brand materials (e.g., business cards, packaging, or apparel tags). Photorealistic rendering with natural window lighting and realistic shadows. Neutral background. Logo should appear printed or embossed naturally.
```

---

### **Asset 4: Logo Variations** 🔄 **OPTIONAL**
**Trigger:** User explicitly requests "variations", "different backgrounds", "color versions"
**Execution:** Generate AFTER Asset 1 completes.
**reference_image:** ✅ **REQUIRED** - Use Asset 1's output image URL.

**Prompt Template:**
```
Create a logo variation showcase in a clean grid. Show the same logo on: 1. Original style, 2. Light background, 3. Dark background, 4. Monochrome (black/white). Do NOT redesign; only adjust colors for visibility.
```

---

### **Other Assets (Custom User Requirements)** 🎯 **OPTIONAL**

**Trigger:** User explicitly mentions specific use cases (e.g., social media, product packaging, stationery, signage, etc.)

**Execution Rules:**
- **Timing:** Generate AFTER Primary Logo completes
- **reference_image:** ✅ **REQUIRED** - Use Primary Logo URL to maintain design consistency
- **Quantity:** Generate as many as user explicitly requests

**Prompt Approach:**
Apply the logo from Asset 1 to the user's specified context. Use the logo as-is without redesigning. Ensure realistic rendering with appropriate lighting, shadows, and materials

---

## 7. Design Principles (Quality Control)

- **⚠️ Contrast (CRITICAL):** Background color MUST provide high contrast with all logo elements
  - Check contrast ratio: Logo should be clearly visible at small sizes (32px)
  - Light logos require dark backgrounds; dark logos require light backgrounds
  - Test: If you squint, can you still see the logo? If not, adjust background color
- **Symbolism:** Icons must be **abstract/symbolic** (e.g., a sliver for "speed"), not literal objects.
- **Negative Space:** Ensure the "empty" space is as meaningful as the "filled" space in flat styles.
- **Proportions:** Icon-to-Text ratio 3:2. Margins 15-20% clear space.
- **Avoid Vague Terms:** Use specific visual terms like "museum-quality", "precision-cut", or "letterpress texture" instead of "beautiful" or "professional".

---

## 8. Optimization Priority

If the result is unsatisfactory, refine in this order:
1. **⚠️ Background-Logo Contrast (FIRST CHECK):** Ensure background color provides high contrast with logo
   - Light logo + Dark background or Dark logo + Light background
   - If logo is barely visible, change background to opposite tone
2. **Accio Concept:** Restate the symbolic meaning more vividly.
3. **Material/Color Contrast:** Adjust logo material properties for better definition.
4. **Lighting:** Strengthen rim light or adjust key light angle (for 3D styles).
5. **Simplicity:** Remove small details to improve recognizability at small sizes.
6. **Typography:** Match weight and style to the overall brand vibe.
