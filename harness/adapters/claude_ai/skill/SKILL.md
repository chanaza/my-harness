---
name: harness-claude-ai-export
description: Keep the user's claude.ai data (chats, projects, memory) saved in their harness. Downloads the claude.ai data export requested last time, then requests a new one. Use when asked to "export claude.ai to my harness", or when a scheduled task runs this skill (every ${EVERY_DAYS} days).
---

# Export claude.ai to the harness

The user's harness (my-harness) saves everything they build with AI outside any
single tool. claude.ai chats and projects can only leave claude.ai through its
official data export, which arrives by e-mail. This skill moves that along.
Work quietly; report only the outcome in one or two sentences.

You need control of the user's browser (or computer). Use the claude.ai account
the user is signed in to; do not sign in to anything else.

## 1. Download the export requested last time

1. Look in the user's e-mail for the most recent message from Anthropic / Claude
   saying their data export is ready (from the last ${EVERY_DAYS} days).
2. If there is one and its link has not expired, open the download link in the
   browser and save the file in: `${WATCH_FOLDER}`
   (its name starts with `data-`; keep the name).
3. If there is none, continue with step 2.

## 2. Request a new export

1. Open https://claude.ai/settings and go to **Privacy**.
2. Choose **Export data** and confirm. An e-mail will arrive later; the next run
   of this skill downloads it.

## Notes

- Never delete or change anything in the account.
- The harness on the computer picks up the downloaded file by itself; nothing
  else is needed.
- If a step fails (e.g. the page looks different), say which step and stop.
