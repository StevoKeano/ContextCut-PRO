# ContextCut PRO — Product Hunt Demo (60s)

**Technique**: One continuous OBS take recorded with Ctrl+F12 AHK hotkey. AHK drives all clicks and typing. You do the voiceover in real time alongside the script — no post-production editing needed other than trimming the start/end.

**Prep** (before recording):
```bash
ssh steve@192.168.137.252
cd ~/contextcut
cp starterKnowledgeFiles/lawyer-* knowledge/
cp starterKnowledgeFiles/base-* knowledge/
./start.sh
```

On Windows: `ssh -L 18787:127.0.0.1:18787 steve@192.168.137.252` then open `http://localhost:18787` in Chrome.

---

## Timing: Narration + AHK actions side by side

| Time | AHK Action | Narration |
|------|------------|-----------|
| **0:00** | Click **Demo Data**. Table populates with 10 rows. | "Every time you ask your local LLM a question, you paste in everything — and watch your context window bloat, or you paste nothing and get answers with no memory of your actual work. ContextCut is different." |
| **0:05** | Scroll through the table. Rows show before/after token counts. | "Look at these real token counts. Before: 64 tokens for the raw query. After: over 1,400 tokens — because ContextCut automatically found and injected relevant context from your knowledge base." |
| **0:09** | Click **Browse Files**. Modal opens showing knowledge base .md files. | "This is the knowledge base — markdown files for your profession. Legal clauses, CPA tax notes, medical guidelines. Drop a file in, it's ingested and searchable within seconds. All local." |
| **0:13** | Press **Escape** to close modal. | "No cloud. No uploads. Your data never leaves your machine." |
| **0:16** | Click model input, then chat input. | — |
| **0:19** | Type: `What are the key terms in this non-compete clause?` | "Let's see it in action. A real question from a real use case." |
| **0:23** | Press **Enter**. Streaming begins. | "The proxy sends the query to Qdrant, finds the three most relevant chunks from the knowledge base, injects them into the prompt, and streams the response back." |
| **0:24→0:42** | Wait for response to stream in. | *Pause narration or add quietly:* "Notice the left panel — it updates live with token counts, compression percentage, and which knowledge files matched." |
| **0:42** | Click **Params ⚙**. Settings panel opens showing temp, top-p, min_score sliders. | "Fine-tune retrieval right here. Min score controls how relevant a chunk must be before injection. Top-K sets how many chunks to inject. Tune these live — no config files, no restarts." |
| **0:49** | Click **Params ⚙** to close panel. | — |
| **0:54** | Click **Demo Data** again. Table refreshes with final state. | "Everything local. Your documents, your queries, your vector database. ContextCut PRO — stop wasting tokens. Inject only what matters." |
| **1:00** | (manual) End recording. Final overlay: `https://api.contextcut-pro.com/promo` | |

---

## Key rules

- **No cuts** — one continuous take works better for ProductHunt. The AHK script pauses naturally between actions giving you clean narration gaps.
- **Numbers are real** — the demo data seed generates actual before/after token counts. Point at them.
- **No terminal clips** — the video is 100% the dashboard UI. No install process, no config files.
- **Call to action** — final frame shows the promo URL. Add this as an overlay in OBS or hold the page on screen.
