cat << 'EOF' > /home/steve/keanapps/CONTEXTCUT-LAB-FACTORY.md
# ContextCut-PRO Standalone HTML Lab Factory (Repeatable SOP)

## 1. Purpose & Trigger Workflow
This document is a **reusable prompt & orchestration blueprint** for generating standalone, interactive 3D/2D single-file HTML science & engineering labs (`Three.js` + `2D Canvas` + `KaTeX`) using `ContextCut-PRO` (`orchestrator.py`).

### How to Use This File
1. Upload or paste this Markdown file into a new session.
2. Provide the following inputs for the next chapter:
   - **Author(s):** (e.g., *John D. Kraus & Daniel A. Fleisch*)
   - **Book Title:** (e.g., *Electromagnetics with Applications*)
   - **Target HTML Filename:** (e.g., `EM-ELECTROSTATICS.html`)
   - **Chapter Number & Title:** (e.g., *Chapter 4: Electrostatics*)
   - **Section Headings:** (List of sections to become interactive modules `mod1` through `modN`)
3. The assistant will generate a **complete, zero-edit deployment package** tailored to that chapter:
   - **Part A:** Baseline single-file HTML template (`TARGET.html`) with the Three.js/2D-Canvas/KaTeX/UI-Controller harness and `/* === UI CONTROLLER === */` anchor.
   - **Part B:** Deterministic validator script (`check_<slug>.py`) enforcing schema invariants, `type: 'check'` compliance, and `node --check` JS syntax validation.
   - **Part C:** Prompt generator script (`generate_<slug>_prompts.py`) writing `/tmp/mod1.txt` .. `/tmp/modN.txt` using the 2-step `write_file("new_module.js")` + Python splice protocol.
   - **Part D:** End-to-end orchestrator runner script (`/tmp/run_<slug>.sh`) pre-configured for Strata/DeepSeek, including pre-flight baseline validation, automatic false-positive rollback recovery, control sanitization, and final verification.
   - **Part E:** `tmux` launch command & live monitoring one-liners.

---

## 2. Non-Negotiable Architecture Rules (Hard-Earned Lessons from Chapter 3)
Every generated artifact, validator, prompt, and runner **MUST** obey all 10 rules below:

1. **Workspace Isolation (`/tmp/<slug>_stage`):**
   - Never run `orchestrator.py` inside `~/keanapps` (causes false `web_app_wiring` failures against unrelated `index.html` files and blocks paths outside workspace root).
   - Stage **only** `<TARGET>.html` and `check_<slug>.py` inside `/tmp/<slug>_stage`, initialize a disposable git repo (`git init` + `user.email` + `user.name` + `baseline` commit), and copy verified outputs back to `~/keanapps/` after each module passes.
2. **Pre-Flight Baseline Validation:**
   - Before starting `mod1`, `/tmp/run_<slug>.sh` must run `python3 "$VALIDATOR"` against the empty baseline HTML shell to prove the `/* === UI CONTROLLER === */` anchor and `<script type="module">` JS pass `node --check` before any LLM tokens are spent.
3. **Zero-Read Inline API Contract (Bypass 32KB Cap & Compaction):**
   - Because multi-module HTML files exceed the 32KB `read_file` limit, every module prompt **must forbid** `read_file`, `grep`, `list_dir`, or slice-printing on `<TARGET>.html`.
   - Instead, embed the exact global API contract (`renderer`, `scene`, `camera`, `content`, `chartEl`, `addArrowField`, `setHud`, module hooks, and `/* === UI CONTROLLER === */` anchor) directly at the top of every prompt.
4. **2-Step `write_file` + Python Splice Protocol (No Shell Escaping Stalls):**
   - Never ask the LLM to pass a multi-line JavaScript module inside a `python3 -c "..."` string or heredoc (causes nested quote failures and 10+ minute generation stalls).
   - **Step 1:** Implementer calls `write_file` to save ONLY the raw `modules.push({...});` JS block into `new_module.js` in the workspace root (no `<script>` tags).
   - **Step 2:** Implementer calls `run_command` with a 1-line Python splice that injects `new_module.js` right before `/* === UI CONTROLLER === */`, removes `new_module.js`, and immediately executes `python3 check_<slug>.py <expected_ids>`.
5. **Timeout & Step Budget Calibration:**
   - At ~6–7.5 tok/s on local inference (`deepseek-v4.1-flash`, `49,152` context), generating a 10–14KB module takes ~8–10 minutes.
   - Always pass `--implementer-max-steps 12`, `--verifier-max-steps 6`, `--max-tokens 16384`, `--verifier-max-tokens 8192`, `--ctx-limit 49152`, `--reasoning low`, `--verifier-reasoning low`, `--reasoning-budget-tokens 256`, and `--no-tts-live`.
6. **Strict Control, HUD & Quiz Schema (Enforced on Every Cycle):**
   - Control objects must use `id:` (never `key:`).
   - Valid control `type` values are strictly `'range'`, `'select'`, and `'check'` — **never `'checkbox'`**. Both `check_<slug>.py` and the post-loop sanitizer enforce this.
   - HUD updates must call the global 3-argument `setHud(titleStr, latexEqStr, rowsArray)` (never 1-arg `setHud([...])` or `this.setHud(...)`).
   - Quiz items must use `answer: 0..3` (never `correct:`).
7. **Deterministic Gatekeeper (`check_<slug>.py`):**
   - Must live inside `/tmp/<slug>_stage` alongside `<TARGET>.html`.
   - Must validate: anchor presence, unique module IDs, exact expected module ID list, `id:` control schema, no `type: 'checkbox'`, 3-arg global `setHud`, `answer:` quiz schema, and `node --check` on the extracted `<script type="module">` block.
8. **Auto-Recovery from False-Positive Orchestrator Rollbacks:**
   - If `orchestrator.py` exits non-zero due to a verifier-sandbox quirk (e.g., verifier running `git status` in a `.git`-stripped copy or `implementer_changed_workspace` on a later cycle) *after* the module already passed `check_<slug>.py` inside `~/.contextcut/orchestrations/`, `/tmp/run_<slug>.sh` automatically recovers the newest verified HTML matching all `$expected` IDs, re-validates it with `check_<slug>.py`, commits it, and continues to the next module without manual intervention.
9. **Scratch File Cleanup Before Git Commit:**
   - Always execute `rm -f "$STAGE"/*.bak* "$STAGE"/new_module.js` before `git commit` so backup files never pollute subsequent cycles or confuse implementer file listings.
10. **Shell Alias Safety:**
    - Always use `command ls -1td` (never bare `ls -td`) when scripting log paths so `ls -l` aliases do not break `tail`.

---

## 3. Standard Prompt Template (Instantiated per Section `mod1`..`modN`)

Every generated `/tmp/mod<K>.txt` file must follow this exact structure:

```text
0. CRITICAL — DO NOT inspect <TARGET_HTML> (no read_file, grep, list_dir, or print slices).
Available globals in <script type="module">:
  - `renderer` (THREE.WebGLRenderer), `scene` (THREE.Scene), `camera` (THREE.PerspectiveCamera), `content` (THREE.Group — add all 3D meshes/groups to `content`), `chartEl` (HTMLCanvasElement 2D)
  - `addArrowField(vectors, color = 0x7fd1ff)` where `vectors` is `[{ origin: THREE.Vector3, dir: THREE.Vector3, len?: number }, ...]` (adds to `content` and tracks geometries in `sharedArrowGeoms`)
  - `setHud(titleStr, latexEqStr, [{ k: 'label', v: 'value' }, ...])`
  - Module hooks: `id`, `title`, `controls: [{ id, label, type, ... }]` (valid `type` values ONLY: `'range'`, `'select'`, `'check'` — NEVER `'checkbox'`), `build()` (populates `content`), `update()` (reads `const st = this.state;`), `tick(dt)` (optional), `lesson: '...'`, `quiz: [{ q, options: [...], answer: 0 }]`
  - Anchor string in file: `/* === UI CONTROLLER === */`
Execution protocol (2 tool calls total):
  - Step 1: Call `write_file` to save ONLY the new `modules.push({...});` JavaScript block to `new_module.js` in the workspace root (no `<script>` tags).
  - Step 2: Call `run_command` with:
      python3 -c "s=open('<TARGET_HTML>',encoding='utf-8').read(); m=open('new_module.js',encoding='utf-8').read(); open('<TARGET_HTML>','w',encoding='utf-8').write(s.replace('/* === UI CONTROLLER === */', m+'\n/* === UI CONTROLLER === */', 1)); import os; os.remove('new_module.js')" && python3 check_<SLUG>.py <CUMULATIVE_MODULE_IDS>
  - Then immediately output "Done." and stop.

1. Add Module <K> (`id: '<MODULE_ID>'`, `title: '<K>. <SECTION_TITLE>'`) to `<TARGET_HTML>`.
2. Physics & Controls:
   - Define the exact equations, physical constants, variables, units, parameter ranges, and presets from this section.
   - Use ONLY `type: 'range'`, `type: 'select'`, or `type: 'check'` in `controls` (NEVER `'checkbox'`).
3. Visuals & HUD:
   - Render the 3D scene geometry and vector fields in `content` using Three.js meshes and `addArrowField(...)` (with optional `tick(dt)` animation).
   - Render the corresponding 2D analytical plot, curve, or diagram on `chartEl`.
   - Call global `setHud(titleStr, latexEqStr, rows)` with properly escaped LaTeX equations and live computed metrics.
4. Lesson & Quiz:
   - Include a concise HTML `lesson` summarizing the physical principles and boundary/limiting cases for <SECTION_TITLE>, plus 2–3 multiple-choice `quiz` items using `answer: 0..3`.
```

---

## 4. Standard Deterministic Validator (`check_<slug>.py`)

```python
import os, re, subprocess, sys, tempfile

TARGET_FILE = "<TARGET_HTML>"
target = TARGET_FILE if os.path.isfile(TARGET_FILE) else f"/home/steve/keanapps/{TARGET_FILE}"
html = open(target, encoding="utf-8").read()
expected_ids = sys.argv[1:]

assert "/* === UI CONTROLLER === */" in html, "Missing UI CONTROLLER anchor"
found_ids = re.findall(r"modules\.push\(\{\s*id:\s*['\"]([^'\"]+)['\"]", html)
assert len(found_ids) == len(set(found_ids)), f"Duplicate module IDs: {found_ids}"
for eid in expected_ids:
    assert eid in found_ids, f"Missing expected module id: {eid}"

mod_section = html.split("const modules = [];")[1].split("/* === UI CONTROLLER === */")[0]
assert not re.search(r"controls:\s*\[[^\]]*?\bkey\s*:", mod_section, re.S), "Found control using key: instead of id:"
assert not re.search(r"type:\s*['\"]checkbox['\"]", mod_section), "Found type: 'checkbox'; must use type: 'check'"
assert "setHud([" not in mod_section, "Found 1-arg setHud([...]); must be setHud(title, eqTex, rows)"
assert "this.setHud(" not in mod_section, "Found this.setHud(...); must call global setHud(...)"
assert not re.search(r"quiz:\s*\[[^\]]*?\bcorrect\s*:", mod_section, re.S), "Found quiz using correct: instead of answer:"

script_body = html.split('<script type="module">')[1].split('</script>')[0]
with tempfile.NamedTemporaryFile(suffix=".mjs", mode="w", encoding="utf-8") as tf:
    tf.write(script_body)
    tf.flush()
    res = subprocess.run(["node", "--check", tf.name], capture_output=True, text=True)
    assert res.returncode == 0, f"JS syntax error:\n{res.stderr}"

print(f"PASS: Verified {len(found_ids)} modules {found_ids}")
```

---

## 5. Standard End-to-End Orchestrator Runner (`/tmp/run_<slug>.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

SLUG="<SLUG>"
STAGE="/tmp/${SLUG}_stage"
TARGET="/home/steve/keanapps/<TARGET_HTML>"
VALIDATOR="/home/steve/keanapps/check_${SLUG}.py"
BASE_URL="[http://192.168.137.1:8080/v1](http://192.168.137.1:8080/v1)"
MODEL="deepseek-v4.1-flash"

rm -rf "$STAGE" && mkdir -p "$STAGE"
cp "$TARGET" "$STAGE/<TARGET_HTML>"
cp "$VALIDATOR" "$STAGE/check_${SLUG}.py"

# Pre-flight check on baseline HTML shell before burning inference cycles
python3 "$STAGE/check_${SLUG}.py"

git -C "$STAGE" init -q
git -C "$STAGE" config user.email "steve@local"
git -C "$STAGE" config user.name "Steve"
git -C "$STAGE" add . && git -C "$STAGE" commit -q -m "baseline"

cd ~/dev/ContextCut-PRO

declare -a MODS=(
  # "mod1:id1"
  # "mod2:id1 id2"
  # ...
)

expected=""
for entry in "${MODS[@]}"; do
  tag="${entry%%:*}"
  expected="${entry#*:}"
  echo "=== Running $tag ==="

  set +e
  python3 orchestrator.py \
    --workspace "$STAGE" \
    --prompt-file "/tmp/${tag}.txt" \
    --base-url "$BASE_URL" \
    --implementer-model "$MODEL" \
    --verifier-model "$MODEL" \
    --reasoning low \
    --verifier-reasoning low \
    --reasoning-budget-tokens 256 \
    --no-tts-live \
    --ctx-limit 49152 \
    --max-cycles 3 \
    --max-tokens 16384 \
    --verifier-max-tokens 8192 \
    --implementer-max-steps 12 \
    --verifier-max-steps 6 \
    --check-command "python3 check_${SLUG}.py $expected"
  rc=$?
  set -e

  # Auto-recover if orchestrator rolled back after a verifier-sandbox false positive
  if [ "$rc" -ne 0 ]; then
    echo "Orchestrator exited $rc on $tag; checking for verified artifact in ~/.contextcut..."
    python3 - "$STAGE/<TARGET_HTML>" $expected << 'PY'
import glob, os, shutil, sys
dest = sys.argv[1]
req_ids = sys.argv[2:]
candidates = [dest] + glob.glob(os.path.expanduser("~/.contextcut/**/EM-*.html"), recursive=True) + glob.glob(os.path.expanduser("~/.contextcut/**/*.html"), recursive=True)
matches = []
for c in set(candidates):
    if not os.path.isfile(c):
        continue
    try:
        txt = open(c, encoding="utf-8").read()
        if all((f"id: '{eid}'" in txt or f'id: "{eid}"' in txt) for eid in req_ids):
            matches.append((os.path.getmtime(c), c))
    except Exception:
        pass
if not matches:
    sys.exit(1)
matches.sort(reverse=True)
print("Recovered verified HTML from:", matches[0][1])
shutil.copy2(matches[0][1], dest)
PY
  fi

  rm -f "$STAGE"/*.bak* "$STAGE"/new_module.js
  python3 "$STAGE/check_${SLUG}.py" $expected
  git -C "$STAGE" add -A && git -C "$STAGE" commit -q -m "$tag"
  cp "$STAGE/<TARGET_HTML>" "$TARGET"
done

# Automatic post-loop control sanitizer (checkbox -> check) & final verification
python3 - << 'PY'
import re
p = "/home/steve/keanapps/<TARGET_HTML>"
html = open(p, encoding="utf-8").read()
head, rest = html.split("const modules = [];", 1)
mods, tail = rest.split("/* === UI CONTROLLER === */", 1)
mods_fixed = re.sub(r"type:\s*['\"]checkbox['\"]", "type: 'check'", mods)
open(p, "w", encoding="utf-8").write(head + "const modules = [];" + mods_fixed + "/* === UI CONTROLLER === */" + tail)
print("Normalized control types to type: 'check'.")
PY

python3 "$VALIDATOR" $expected
echo "ALL MODULES VERIFIED, SANITIZED, AND SYNCED TO $TARGET"
```

---

## 6. Emergency Salvage & Live Monitoring Reference

### Stray `new_module.js` Salvage (If Implementer Times Out After Step 1)
```bash
pkill -f "orchestrator\.py" || true; pkill -f "coding_agent\.py" || true
python3 -c "import os; p='/tmp/<SLUG>_stage/<TARGET_HTML>'; m='/tmp/<SLUG>_stage/new_module.js'; s=open(p,encoding='utf-8').read(); open(p,'w',encoding='utf-8').write(s.replace('/* === UI CONTROLLER === */', open(m,encoding='utf-8').read()+'\n/* === UI CONTROLLER === */', 1)); os.remove(m)"
```

### Live Monitoring (2nd Terminal)
```bash
watch -n 10 'grep -n "id:" /home/steve/keanapps/<TARGET_HTML> | tail -n 20'
tail -f "$(command ls -1td ~/.contextcut/coding_runs/* | head -n 1)/events.jsonl"
```

---

## 7. Assistant Generation Checklist (When User Supplies Chapter Details)
When the user uploads this `.md` file and provides **Author, Book Title, Chapter Title, and Section Headings**, the assistant MUST output in one response:
1. **Baseline HTML Shell (`<TARGET>.html`):** Complete single-file Three.js + 2D Canvas + KaTeX + sidebar/HUD/quiz UI controller with `const modules = [];` and `/* === UI CONTROLLER === */`, pre-branded with the Author, Book Title, and Chapter Title (matching the `EM-TRANSMISSION-LINES.html` / `EMCraft` visual architecture).
2. **Validator (`check_<slug>.py`):** Complete Python check script with the exact chapter module IDs and all schema/syntax assertions from Section 4.
3. **Prompt Builder (`generate_<slug>_prompts.py`):** Complete Python script generating `/tmp/mod1.txt` .. `/tmp/modN.txt` (including a final Capstone/Synthesis & Problems module) with full mathematical formulas, 3D vector/mesh visualizations, `chartEl` plots, `setHud` LaTeX equations, `lesson` HTML, and `quiz` items.
4. **End-to-End Runner Script (`/tmp/run_<slug>.sh`):** Pre-populated with every `modK` entry, pre-flight check, auto-recovery block, post-loop `checkbox` -> `check` sanitizer, and final `$VALIDATOR` pass.
5. **Copy-Paste Launch Command:** Ready-to-run `tmux` execution command (`tmux new -s <slug> 'bash /tmp/run_<slug>.sh 2>&1 | tee /tmp/run_<slug>.log'`).
EOF