---
name: mirror-check
description: Check or create a human-owned MIRROR.md or MIRROR-*.md for drift and misunderstandings. Use whenever the user says "check mirror", "check {particular} mirror", "mirror check", "new mirror", or similar.
disable-model-invocation: true
---

# mirror-check

A MIRROR.md or MIRROR-*.md file is a human-owned mental mirror that AI agents check but never edit.
Lifecycle: human edits and/or project changes → agent fact checks → repeat.
Human advice: manually edit, rephrase over copying, compress over logging.
Agent rules: focus on drift/misunderstandings, not exhaustiveness, never edit.

## Steps

1. Use conversation context and/or skill args to find and read an appropriate existing MIRROR.md or MIRROR-*.md file.
  - Even if the user asks you to create a new mirror file, consider looking for one the user may not be aware of.
  - If you cannot find an approprite mirror file, read [create.md](./create.md) and continue from those instrucions.
2. Fact check the mirror file.
3. Discuss your findings. Focus on drift and misunderstandings. Do not worry about exhaustiveness or typos.
