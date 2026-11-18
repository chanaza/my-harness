---
name: harness-claude-ai-export
description: Keep the user's claude.ai data (chats, projects, memory) saved in their harness. Two modes - "request" asks claude.ai for a data export; "download" saves the export from the e-mail into the folder the harness watches. Use when a scheduled task asks to run harness-claude-ai-export (request every ${EVERY_DAYS} days, download ${DOWNLOAD_AFTER} hours later), or when the user asks to export claude.ai to their harness.
---

# Export claude.ai to the harness

The user's harness (my-harness) saves everything they build with AI outside any
single tool. claude.ai chats and projects can only leave claude.ai through its
official data export, which arrives by e-mail. This skill moves that along.
Work quietly; report only the outcome in one or two sentences.

**Which mode:** "set up my harness export" means setup mode. A scheduled task
says "request" or "download". Anything else: do both, first "download", then
"request".

## Setup mode: create the schedule (once per account)

Create two scheduled tasks in Cowork (use the scheduling capability):

1. Name "Harness - request claude.ai export", every ${EVERY_DAYS} days, prompt:
   "Run the harness-claude-ai-export skill in request mode."
2. Name "Harness - download claude.ai export", every ${EVERY_DAYS} days,
   ${DOWNLOAD_AFTER} hours after the first, prompt:
   "Run the harness-claude-ai-export skill in download mode."

Then run request mode once now, and tell the user in one sentence that it is set
up and the first export will be saved within a few hours.

You need control of the user's browser (or computer). Use the claude.ai account
the user is signed in to; do not sign in to anything else.

## Download mode: save the export that was requested

1. Look in the user's e-mail for the most recent message from Anthropic / Claude
   saying their data export is ready (from the last ${EVERY_DAYS} days).
2. If there is one and its link has not expired, open the download link in the
   browser and save the file in: `${WATCH_FOLDER}`
   (its name starts with `data-`; keep the name).
3. If there is none yet, say so and stop (the next download run will find it).

## Request mode: ask for a new export

1. Open https://claude.ai/settings and go to **Privacy**.
2. Choose **Export data** and confirm. An e-mail with a download link arrives
   later; the download run (${DOWNLOAD_AFTER} hours later) saves it.

## Notes

- Never delete or change anything in the account.
- The harness on the computer picks up the downloaded file by itself; nothing
  else is needed.
- If a step fails (e.g. the page looks different), say which step and stop.
