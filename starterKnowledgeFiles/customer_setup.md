# Customer Setup Guide

## Starter Files Overview

The `starterKnowledgeFiles/` folder (at `~/contextcut/starterKnowledgeFiles/`) contains starter files organized by profession.
**You must customize these files** for your specific practice area.

## Required Customization

### Step 1: Delete files from other professions

Only keep files matching YOUR profession:

| Your Profession | Keep prefix | Delete prefixes |
|----------------|-------------|-----------------|
| Lawyer — Small Business | `lawyer-smb-*`, `base-*` | `lawyer-lit-*`, `lawyer-re-*`, `cpa-*`, `doctor-*`, `realtor-*`, `advisor-*`, `architect-*`, `tech-*`, `consultant-*` |
| Lawyer — Litigation | `lawyer-lit-*`, `base-*` | `lawyer-smb-*`, `lawyer-re-*`, `cpa-*`, `doctor-*`, etc. |
| Lawyer — Real Estate | `lawyer-re-*`, `base-*` | `lawyer-smb-*`, `lawyer-lit-*`, `cpa-*`, `doctor-*`, etc. |
| CPA — Personal | `cpa-personal-*`, `base-*` | `cpa-smb-*`, `cpa-corp-*`, `lawyer-*`, `doctor-*`, etc. |
| CPA — Small Business | `cpa-smb-*`, `base-*` | `cpa-personal-*`, `cpa-corp-*`, `lawyer-*`, `doctor-*`, etc. |
| CPA — Corporate | `cpa-corp-*`, `base-*` | `cpa-personal-*`, `cpa-smb-*`, `lawyer-*`, `doctor-*`, etc. |
| Doctor | `doctor-*`, `base-*` | `lawyer-*`, `cpa-*`, `realtor-*`, `advisor-*`, etc. |
| Realtor | `realtor-*`, `base-*` | `lawyer-*`, `cpa-*`, `doctor-*`, etc. |

### Step 2: Trim BASE files

The `base-*.md` files contain sections for multiple professions (e.g., `base-DEADLINES.md` has legal, tax, and healthcare deadlines). **Delete all sections that don't apply to you.** Each BASE file should end up with only content relevant to your single discipline.

**Example**: A doctor should edit `base-DEADLINES.md` to keep only the "Healthcare" section and remove "Legal" and "Tax".

### Step 3: Add your own knowledge

The starter files contain frameworks and references to get you started. Replace generic content with:
- Your preferred workflows and templates
- State-specific laws/regulations (for your jurisdiction)
- Your frequently-used clauses, forms, or calculations
- Client communication templates you actually use

### Step 4: Verify ingestion

After customizing, the watcher automatically re-ingests. Check with:
```bash
python3 -c "
from qdrant_client import QdrantClient
qc = QdrantClient(host='localhost', port=6333)
cnt = qc.count('contextcut', exact=True)
print(f'Qdrant points: {cnt.count} (should match your file count)')
for p in qc.scroll('contextcut', limit=50)[0]:
    print(f'  {p.payload.get(\"filename\",\"?\")}')
"
```

## Best Practices
- Keep files focused on a single topic (one .md per subject area)
- Use clear headings (the AI uses them for retrieval context)
- Add real citations from your jurisdiction's law/regulations
- Update regularly as laws/regulations change
