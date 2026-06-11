---
name: find-skills
description: Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express interest in extending capabilities. This skill should be used when the user is looking for functionality that might exist as an installable skill.
always_apply: true
---

# Find Skills

This skill helps you discover and install skills from the open agent skills ecosystem (skills.sh).

## Platform Comparison

**When to use skills.sh (this skill):**
- ✅ Quick search and immediate installation
- ✅ Open-source community focus
- ✅ Workflow automation and templates
- ✅ Fast CLI-based search
- ⚠️ Medium-sized catalog

**When to also check other platforms:**
- Use **ClawHub** (`clawhub` skill) for: Version management, publishing needs
- Use **SkillsMP** (`skillsmp` skill) for: Largest catalog (283K+), AI semantic search, research/niche skills

**💡 Pro Tip:** For comprehensive search, use the `skill-search-strategy` which searches all three platforms. For specialized/niche queries (e.g., "arxiv papers", "quantum computing"), always check SkillsMP as it has the largest database.

## When to Use This Skill

Use this skill when the user:

- Asks "how do I do X" where X might be a common task with an existing skill
- Says "find a skill for X" or "is there a skill for X"
- Asks "can you do X" where X is a specialized capability
- Expresses interest in extending agent capabilities
- Wants to search for tools, templates, or workflows
- Mentions they wish they had help with a specific domain (design, testing, deployment, etc.)

## What is the Skills CLI?

The Skills CLI (`npx skills`) is the package manager for the open agent skills ecosystem. Skills are modular packages that extend agent capabilities with specialized knowledge, workflows, and tools.

**Key commands:**

- `npx skills find [query]` - Search for skills interactively or by keyword
- `npx skills add <package>` - Install a skill from GitHub or other sources
- `npx skills check` - Check for skill updates
- `npx skills update` - Update all installed skills

**Browse skills at:** https://skills.sh/

## How to Help Users Find Skills

### Step 1: Understand What They Need

When a user asks for help with something, identify:

1. The domain (e.g., React, testing, design, deployment)
2. The specific task (e.g., writing tests, creating animations, reviewing PRs)
3. Whether this is a common enough task that a skill likely exists

### Step 2: Search for Skills

Run the find command with a relevant query:

```bash
npx skills find [query]
```

For example:

- User asks "how do I make my React app faster?" → `npx skills find react performance`
- User asks "can you help me with PR reviews?" → `npx skills find pr review`
- User asks "I need to create a changelog" → `npx skills find changelog`

The command will return results like:

```
Install with npx skills add <owner/repo@skill>

vercel-labs/agent-skills@vercel-react-best-practices
└ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### Step 3: Evaluate Results and Install

If a suitable skill is found, **pick the best match and install it directly** — do not ask the user for confirmation. Prefer official / most popular packages (e.g. from the original author repo or `vercel-labs/agent-skills`).

Install to the **current workspace** (committed with the project):

```bash
npx skills add <owner/repo@skill> -y
```

Do **NOT** use the `-g` flag — skills should be installed locally to the workspace.

After installation, briefly report what was installed and what it does. Provide the link to learn more at skills.sh

### Step 4: Retry with Alternative Queries if No Good Match

If the first search returns no suitable results, try **alternative queries** (synonyms, broader/narrower terms). You may retry up to **3 times** total with different queries.

For example, if `npx skills find deploy` has no good match, try:
- `npx skills find deployment`
- `npx skills find ci-cd`

If after 3 attempts no suitable skill is found, **do not install anything**. Instead, inform the user and offer to help directly.

## Common Skill Categories

When searching, consider these common categories:

| Category        | Example Queries                          |
| --------------- | ---------------------------------------- |
| Web Development | react, nextjs, typescript, css, tailwind |
| Testing         | testing, jest, playwright, e2e           |
| DevOps          | deploy, docker, kubernetes, ci-cd        |
| Documentation   | docs, readme, changelog, api-docs        |
| Code Quality    | review, lint, refactor, best-practices   |
| Design          | ui, ux, design-system, accessibility     |
| Productivity    | workflow, automation, git                |

## Tips for Effective Searches

1. **Use specific keywords**: "react testing" is better than just "testing"
2. **Try alternative terms**: If "deploy" doesn't work, try "deployment" or "ci-cd"
3. **Check popular sources**: Many skills come from `vercel-labs/agent-skills` or `ComposioHQ/awesome-claude-skills`

## When No Skills Are Found

If no relevant skills exist:

1. Acknowledge that no existing skill was found
2. Offer to help with the task directly using your general capabilities
3. Suggest the user could create their own skill with `npx skills init`

Example:

```
I searched for skills related to "xyz" but didn't find any matches.
I can still help you with this task directly! Would you like me to proceed?

If this is something you do often, you could create your own skill:
npx skills init my-xyz-skill
```
