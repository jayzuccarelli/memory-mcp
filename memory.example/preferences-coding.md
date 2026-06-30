---
id: preferences-coding
type: preference
scope: global
description: Coding language, style, and review preferences
created: 2026-06-30
updated: 2026-06-30
tags: [coding, style]
---

# Coding preferences

<!-- These are an example. Replace with your own. The point is to give the
     LLM enough guidance to write code the way you actually want it, on the
     first try, without you having to re-explain in every chat. -->

## Languages
- Python preferred for prototypes and personal tooling
- TypeScript when the runtime needs to be Node / Cloudflare / Vercel

## Style
- Terse code, minimal comments — only comment the *why*, never the *what*
- No premature abstractions; three similar lines beat a half-baked helper
- No backwards-compat shims when you can just change the code

## What to avoid
- Vector DBs / heavy infra when files would do
- Speculative features and "future-proofing" hooks

## Related
- [[identity]]
