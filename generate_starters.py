#!/usr/bin/env python3
"""Generate ContextCut-PRO starter knowledge base files."""
import os
from pathlib import Path

BASE = Path(__file__).parent / "starterKnowledgeFiles"
BASE.mkdir(parents=True, exist_ok=True)

files = {}

# ═══════════════════════════════════════════════════════════════
# BASE FILES (shared across all professions)
# ═══════════════════════════════════════════════════════════════

files["base-SKILL.md"] = """# ContextCut-PRO Prompting Skills

## Overview
Core techniques for crafting effective queries that retrieve maximum relevant context from your knowledge base.

## Key Techniques

### 1. Context-First Prompting
- State your **role** first: "You are a [profession] with [specialization]"
- Define the **document type**: "Draft a [contract|memo|brief|letter]"
- Specify **jurisdiction/authority**: "Under [Federal Rules|IRC §|State law]"

### 2. Reference Anchoring
- Cite specific filenames: "Per CONTRACT.md, review the indemnification clause..."
- Reference prior analysis: "Building on the analysis in REVIEW.md..."

### 3. Multi-Step Reasoning
- Break complex tasks: "First summarize the issue, then identify applicable law, then apply facts"
- Request citations: "Cite the specific rule or code section for each conclusion"

### 4. Constraint Injection
- Word limits: "In 500 words or less"
- Format: "As a bullet-point memo suitable for partner review"
- Audience: "Explain to a client without legal expertise"

## Example Workflows
See profession-specific files for tailored examples.
"""

files["base-RESEARCH.md"] = """# Research Methodology

## Primary Source Hierarchy
1. **Statutory/Regulatory** - Controlling legislation and regulations
2. **Binding Precedent** - Cases from controlling jurisdiction
3. **Persuasive Authority** - Cases from other jurisdictions, secondary sources
4. **Administrative Guidance** - Agency rulings, revenue procedures, advisory opinions
5. **Treatises** - Restatements, practice guides, law review articles

## Research Workflow
1. **Issue Identification** → Pinpoint the precise legal/tax/regulatory question
2. **Source Selection** → Identify which authorities govern
3. **Search Execution** → Use targeted queries with specific code sections
4. **Validation** → Shepardize/KeyCite all cases; check for amendments
5. **Synthesis** → Organize findings by issue, noting conflicts and trends
6. **Application** → Apply law to specific facts; identify gaps

## Citation Standards
- **Legal**: Bluebook (21st ed.) / ALWD Guide
- **Tax**: IRC § section.subsection.paragraph.subparagraph.clause
- **Medical**: AMA Manual of Style
- **Accounting**: AICPA Professional Standards

## ContextCut Query Examples
- "Find all materials discussing IRC §199A qualified business income deduction"
- "What are the pleading standards under FRCP 8(a) for a fraud claim?"
- "Summarize HIPAA privacy rule requirements for patient authorization forms"
"""

files["base-DRAFTING.md"] = """# Document Drafting Best Practices

## Universal Principles
- **Clarity**: Short sentences, active voice, defined terms
- **Precision**: Avoid ambiguity; use consistent terminology throughout
- **Structure**: Logical organization with headings and defined sections
- **Risk Allocation**: Each clause serves a clear purpose

## Drafting Process
1. **Outline** - Identify all necessary sections and clauses
2. **First Draft** - Focus on substance over perfection
3. **Review Cycle** - Check for internal consistency, missing provisions
4. **Authority Check** - Verify all citations and legal standards
5. **Final Polish** - Grammar, formatting, cross-references

## Standard Sections (varies by document type)
- Parties and Recitals
- Definitions
- Consideration / Payment Terms
- Representations and Warranties
- Covenants
- Conditions Precedent
- Termination
- Dispute Resolution
- General Provisions (boilerplate)

## ContextCut Prompt Patterns
- "Draft a [document type] for [scenario] under [governing law]"
- "Review this clause for [specific risk]: [clause text]"
- "Compare [standard form] with [alternative approach]"

See profession-specific templates for tailored provisions.
"""

files["base-REVIEW.md"] = """# Document Review and Analysis Frameworks

## Risk Assessment Matrix

| Risk Level | Description | Action Required |
|------------|-------------|-----------------|
| Critical | Invalidates core purpose | Must revise |
| High | Creates material liability | Strongly recommend revision |
| Medium | Non-standard but acceptable | Flag for client |
| Low | Preference issue | Note only |
| Informational | No material impact | No action |

## Red Flags by Category
- **Ambiguity**: "reasonable," "best efforts" without definition
- **Missing Terms**: No termination clause, no governing law
- **One-Sided**: All remedies for one party only
- **Auto-Renewal**: Evergreen clauses without notice periods
- **Indemnification**: Unlimited or without procedural protections

## Review Methodology
1. **Purpose Check** - Does document achieve client's goal?
2. **Risk Scan** - Identify high-risk provisions
3. **Gap Analysis** - Missing necessary terms
4. **Consistency Check** - Internal conflicts
5. **Authority Check** - Legal/regulatory compliance

## ContextCut Prompts
- "Identify all one-sided provisions in this [document type]"
- "Compare these [clause type] options and recommend"
- "Flag any provisions inconsistent with [statute/regulation]"
"""

files["base-ETHICS.md"] = """# Professional Ethics and Confidentiality

## Universal Ethical Obligations
- **Confidentiality** - Protect client information (ABA Model Rule 1.6 / HIPAA / AICPA Code)
- **Competence** - Maintain relevant knowledge and skill
- **Communication** - Keep client reasonably informed
- **Conflicts** - Identify and resolve conflicts of interest
- **Candor** - Truthfulness to tribunals and third parties

## Confidentiality & AI Tools
- Never input PII, PHI, or privileged information into public AI systems
- ContextCut-PRO runs locally — no data leaves your machine
- Verify all AI-generated citations before filing or sending
- Treat AI output as a first draft requiring professional review

## Jurisdiction-Specific Notes
- **State variations**: Check your state's ethics opinions on AI use
- **ABA Formal Opinion 512**: Addresses generative AI use by lawyers
- **CPA**: AICPA Code of Professional Conduct ET §1.700.001 (Confidentiality)

## Best Practices
- Document your use of AI tools (prompts, outputs, verification steps)
- Never delegate professional judgment to AI
- Maintain billing transparency if using AI in client work
"""

files["base-COMMUNICATION.md"] = """# Client Communication Templates

## Communication Principles
- Know your audience (sophistication level, familiarity with subject)
- Lead with the answer, then explain reasoning
- Use plain language for clients; technical precision for peers
- Set clear expectations on timelines and next steps

## Common Communication Types
1. **Engagement Letters** - Scope, fees, limitations, termination
2. **Status Updates** - Progress, developments, next steps
3. **Strategy Memos** - Analysis, options, recommendations
4. **Opinion Letters** - Legal/tax conclusions with supporting analysis
5. **Demand Letters** - Factual summary, legal position, proposed resolution

## Tone Matrix

| Audience | Urgent Matter | Routine Matter | Educational |
|----------|---------------|----------------|-------------|
| Client | Direct, action-oriented | Reassuring, informative | Patient, explanatory |
| Opposing Counsel | Professional, firm | Cordial, efficient | N/A |
| Court/Ribunal | Formal, precise | Formal, concise | N/A |
| Regulator | Cooperative, thorough | Compliant, complete | N/A |
"""

files["base-COMPLIANCE.md"] = """# Regulatory Compliance Frameworks

## Compliance Architecture
1. **Identify** - Inventory all applicable regulations
2. **Assess** - Evaluate current compliance posture
3. **Remediate** - Address gaps and deficiencies
4. **Monitor** - Track regulatory changes and internal adherence
5. **Report** - Document and disclose as required

## Common Regulatory Domains
- **Data Privacy**: GDPR (EU), CCPA (CA), HIPAA (healthcare)
- **Financial**: SEC, FINRA, SOX, AML/KYC, Dodd-Frank
- **Employment**: FLSA, OSHA, FMLA, Title VII, ADA
- **Environmental**: EPA, RCRA, Clean Water Act, Clean Air Act
- **Healthcare**: CMS, HIPAA, Stark Law, Anti-Kickback Statute
- **Tax**: IRS, state taxing authorities, international tax treaties

## Compliance Program Elements
- Written policies and procedures
- Designated compliance officer
- Training and education
- Monitoring and auditing
- Reporting and whistleblower protections
- Enforcement and discipline
- Response and remediation

## ContextCut Prompts
- "List all regulatory filings required for [business type] in [jurisdiction]"
- "Draft a compliance checklist for [regulation] focusing on [aspect]"
- "Summarize recent changes to [regulation] effective [date]"
"""

files["base-DEADLINES.md"] = """# Professional Deadline Management

## Critical Deadlines by Profession

### Legal
| Deadline Type | Time Period | Authority |
|---------------|-------------|-----------|
| Answer to complaint | 21 days after service | FRCP 12(a)(1)(A) |
| Notice of appeal (civil) | 30 days after judgment | FRAP 4(a)(1)(A) |
| Summary judgment response | 21 days after motion | FRCP 56(c)(1)(C) |
| Expert disclosure | As per scheduling order | FRCP 26(a)(2) |
| Statute of limitations | Varies by claim (1-6 yrs typically) | State law |

### Tax
| Deadline | Date | Key Detail |
|----------|------|------------|
| Individual return filing | April 15 | IRC §6072(a) |
| Corporate return filing | March 15 (calendar yr) | IRC §6072(b) |
| Extension deadline | October 15 | IRC §6081 |
| Estimated tax payments | Quarterly: Apr 15, Jun 15, Sep 15, Jan 15 | IRC §6654 |
| S-Corp election | By day 75 of tax year | IRC §1362(b) |
| 1031 exchange identification | 45 days after closing | IRC §1031(a)(3)(A) |

### Healthcare
| Deadline | Requirement | Authority |
|----------|-------------|-----------|
| HIPAA breach notification | 60 days from discovery | 45 CFR §164.408 |
| CLIA certification renewal | Every 2 years | 42 CFR §493.55 |
| Medicare enrollment | Prior to services | 42 CFR §424.520 |

## Calendar Management Tips
- Use backward planning from the deadline
- Build in buffer for unexpected delays
- Track all deadlines in a centralized system
- Set internal deadlines 25% earlier than actual deadlines
- Confirm receipt of all filings with timestamped proof
"""

# ═══════════════════════════════════════════════════════════════
# LAWYER — SMALL BUSINESS
# ═══════════════════════════════════════════════════════════════

files["lawyer-smb-ENTITY.md"] = """# Business Entity Selection and Formation

## Entity Comparison Matrix

| Factor | Sole Proprietorship | LLC | S-Corp | C-Corp |
|--------|-------------------|-----|--------|--------|
| Liability | Personal | Limited | Limited | Limited |
| Taxation | Personal | Pass-through | Pass-through | Double |
| Formalities | None | Minimal | Moderate | High |
| Ownership | Single | Any number | ≤100, US only | Unlimited |
| Fundraising | Difficult | Moderate | Moderate | Easy |
| Self-Employment Tax | All net income | All net income | Reasonable salary only | N/A |

## Key Considerations
- **Liability Protection**: LLC and corporations shield personal assets (see *Merritt v. O.E. McIntyre*, 86 N.E. 57 (NY 1908) — corporate veil doctrine)
- **Tax Pass-Through**: LLC/S-Corp avoids double taxation (IRC §701-777 partnerships; Subchapter S)
- **Qualified Business Income Deduction**: IRC §199A — up to 20% deduction for pass-through entities
- **Fringe Benefits**: S-Corp >2% shareholder-employees — benefits taxed as distributions (IRC §1372)

## State-Specific Notes
- LLC formation requires Articles of Organization filed with Secretary of State
- Operating Agreement recommended (not always required by statute)
- Registered Agent required in each state of qualification
- Foreign qualification needed for multi-state operations

## ContextCut Prompts
- "Compare LLC vs S-Corp for a [profession] earning $[amount] annually"
- "Draft an LLC Operating Agreement for a single-member [state] LLC"
- "What are the ongoing compliance requirements for a Delaware C-Corp operating in [state]?"
"""

files["lawyer-smb-CONTRACT.md"] = """# Small Business Contracts

## Essential Contract Types
1. **Services Agreement** — Professional services, scope, payment, termination
2. **Independent Contractor Agreement** — IC vs. employee classification
3. **Non-Disclosure Agreement** — Unilateral and mutual forms
4. **Terms of Service** — For SaaS and e-commerce businesses
5. **Partnership Agreement** — Ownership, profit sharing, dispute resolution

## Independent Contractor Classification
- **IRS 20-Factor Test**: Control over work, financial arrangement, relationship
- **Economic Reality Test**: *Hopkins v. Cornerstone America*, 545 F.3d 338 (5th Cir. 2008)
- **ABC Test**: Some states (e.g., CA — *Dynamex Operations West, Inc. v. Superior Court*, 416 P.3d 1 (Cal. 2018))
- **DOL Final Rule (2024)**: Updated independent contractor analysis under FLSA
- Misclassification risks: Back taxes, penalties, overtime liability

## Key Clauses
- **Indemnification**: Mutual vs. one-sided; limits; defense obligations
- **Limitation of Liability**: Cap on damages; exclusion of consequential damages
- **Dispute Resolution**: Arbitration clause (FAA §2, 9 U.S.C. §2); choice of law/venue
- **Force Majeure**: Specific events; notice requirements; termination rights
- **Termination**: For cause, for convenience, notice periods, post-termination obligations

## ContextCut Prompts
- "Draft an independent contractor agreement for a [role] under [state] law"
- "Review this indemnification clause for gaps: [clause text]"
- "Compare arbitration vs. litigation provisions for a [state] services agreement"
"""

files["lawyer-smb-EMPLOYMENT.md"] = """# Employment Law for Small Businesses

## Key Federal Statutes
- **FLSA** (29 U.S.C. §201-219): Minimum wage ($7.25/hr), overtime (1.5× for >40 hrs), exemptions
- **FMLA** (29 U.S.C. §2601-2654): 12 weeks unpaid leave for covered employers (≥50 employees)
- **Title VII** (42 U.S.C. §2000e): Anti-discrimination for ≥15 employees
- **ADA** (42 U.S.C. §12101): Reasonable accommodations for ≥15 employees
- **ADEA** (29 U.S.C. §621): Age discrimination for ≥20 employees
- **OSHA** (29 U.S.C. §651): Workplace safety — all employers
- **IRCA** (8 U.S.C. §1324a): I-9 verification for all employees
- **COBRA** (29 U.S.C. §1161-1169): Continued health coverage for ≥20 employees

## State Law Variations
- At-will employment vs. good cause termination
- Paid sick leave requirements (increasingly common at state level)
- Non-compete restrictions (FTC Non-Compete Rule; state-specific bans)
- Wage payment frequency and final paycheck timing

## Essential Documents
- Employee Handbook
- Job Descriptions (with essential functions for ADA)
- Offer Letters (at-will disclaimers)
- Separation Agreements and General Releases (Older Workers Benefit Protection Act — 29 U.S.C. §626(f))

## ContextCut Prompts
- "Draft an employee handbook section on [policy topic] compliant with [state] law"
- "What are the overtime exemption requirements for an administrative employee under FLSA?"
- "Review this termination scenario for wrongful discharge risk under [state] law"
"""

files["lawyer-smb-IP.md"] = """# Intellectual Property for Small Business

## IP Protection Types

| Type | Protection | Duration | Federal Law |
|------|------------|----------|-------------|
| Trademark | Brand identifiers (names, logos, slogans) | 10 yrs, renewable | Lanham Act, 15 U.S.C. §1051 |
| Copyright | Original works of authorship | Life + 70 yrs / 95 yrs corporate | 17 U.S.C. §101 |
| Patent | Inventions, processes, designs | 20 yrs (utility) / 15 yrs (design) | 35 U.S.C. §101 |
| Trade Secret | Confidential business information | Indefinite (if protected) | DTSA, 18 U.S.C. §1836 |

## Key Considerations for Small Business
- **Trademark**: Use-based rights (common law) vs. federal registration (constructive notice nationwide)
- **Copyright**: Automatic upon creation; registration required to sue
- **Trade Secrets**: Must take reasonable measures to protect — *eBay v. Bidder's Edge*, 100 F. Supp. 2d 1058 (N.D. Cal. 2000)
- **Work Made for Hire**: IP ownership for contractors — must have written agreement (17 U.S.C. §101)

## Client IP Checklist
- Audit existing IP assets
- Clear brand names before investing (trademark search)
- Register key trademarks (USPTO TEAS system)
- Use confidentiality agreements with employees and contractors
- Include IP assignment clauses in all relevant agreements
- Monitor for infringement (online, marketplace, domain names)

## ContextCut Prompts
- "Conduct a trademark clearance analysis for the mark '[name]' for [goods/services]"
- "Draft a work-made-for-hire and IP assignment clause for an independent contractor agreement"
- "What steps must a [state] business take to protect trade secrets under the DTSA?"
"""

files["lawyer-smb-REGULATORY.md"] = """# Business Regulatory Compliance

## Licensing and Permits
- **Federal**: Industry-specific (FDA, FCC, DOT, ATF)
- **State**: Professional licenses, sales tax permits, environmental permits
- **Local**: Business licenses, zoning permits, health department approvals
- **Industry-Specific**: SEC (financial), FINRA (broker-dealer), NFA (futures)

## Privacy Regulations
- **CCPA/CPRA** (Cal. Civ. Code §1798.100): Applies to for-profit businesses meeting thresholds
- **GDPR**: Applies if targeting EU residents (Regulation (EU) 2016/679)
- **State Privacy Laws**: Virginia (VCDPA), Colorado (ColoPA), Connecticut (CTDPA), Utah (UCPA)
- **GLBA** (15 U.S.C. §6801): Financial institution privacy requirements
- **COPPA** (15 U.S.C. §6501): Children's online privacy (under 13)

## Advertising and Marketing
- **FTC Act §5** (15 U.S.C. §45): Prohibits unfair/deceptive acts
- **CAN-SPAM Act** (15 U.S.C. §7701): Commercial email requirements
- **TCPA** (47 U.S.C. §227): Telemarketing and text message restrictions
- **Endorsement Guides**: FTC rules on testimonials and influencers

## ContextCut Prompts
- "List all federal, state, and local licenses required for a [business type] in [city/state]"
- "Draft a CCPA-compliant privacy policy for a small business that [collects/does not collect] personal information"
- "Is this email marketing campaign compliant with CAN-SPAM? [describe campaign]"
"""

# ═══════════════════════════════════════════════════════════════
# LAWYER — LITIGATION
# ═══════════════════════════════════════════════════════════════

files["lawyer-lit-PLEADING.md"] = """# Pleading Standards

## Federal Rules of Civil Procedure

### FRCP 8(a) — Claim for Relief
A pleading must contain:
1. **Jurisdiction** — Basis for subject matter jurisdiction
2. **Statement of Claim** — Short and plain statement showing entitlement to relief
3. **Demand for Relief** — Specific relief sought

### FRCP 8(b) — Defenses and Denials
- Denials must fairly respond to substance of allegation
- Lack of knowledge — operates as denial
- Affirmative defenses must be stated (FRCP 8(c))

### FRCP 9 — Heightened Pleading
- **Fraud/Mistake**: Must state with particularity (FRCP 9(b))
  - *Bell Atlantic Corp. v. Twombly*, 550 U.S. 544 (2007) — plausibility standard
  - *Ashcroft v. Iqbal*, 556 U.S. 662 (2009) — plausibility requires factual content
- **Special Damages**: Must be specifically stated

### FRCP 11 — Signing and Sanctions
- Attorney certification of reasonable inquiry
- No improper purpose, no frivolous arguments
- Sanctions available (motion or court-initiated)
- 21-day safe harbor for withdrawal/ correction

### FRCP 12 — Defenses and Motions
| Motion | Ground |
|--------|--------|
| 12(b)(1) | Lack of subject-matter jurisdiction |
| 12(b)(2) | Lack of personal jurisdiction |
| 12(b)(3) | Improper venue |
| 12(b)(4) | Insufficient process |
| 12(b)(5) | Insufficient service of process |
| 12(b)(6) | Failure to state a claim upon which relief can be granted |
| 12(b)(7) | Failure to join a necessary party |
| 12(c) | Judgment on the pleadings |
| 12(e) | More definite statement |
| 12(f) | Strike |

## ContextCut Prompts
- "Draft a complaint for [claim type] based on the following facts: [facts]"
- "What are the elements of a [claim] claim under [state] law?"
- "Does this complaint satisfy the plausibility standard under Twombly/Iqbal? [complaint text]"
"""

files["lawyer-lit-DISCOVERY.md"] = """# Discovery Practice

## FRCP Discovery Framework

### Scope of Discovery (FRCP 26(b)(1))
Parties may obtain discovery regarding any nonprivileged matter relevant to any party's claim or defense and proportional to the needs of the case.

### Proportionality Factors (FRCP 26(b)(1))
1. Importance of the issues at stake
2. Amount in controversy
3. Parties' relative access to relevant information
4. Parties' resources
5. Importance of the discovery in resolving the issues
6. Whether burden/expense outweighs likely benefit

### Required Disclosures (FRCP 26(a))
1. **Initial** (26(a)(1)): Names, documents, damages computation, insurance
2. **Expert** (26(a)(2)): Written report — retained experts; summary — non-retained
3. **Pretrial** (26(a)(3)): Witnesses, exhibits, depositions, objections

### Discovery Tools
| Tool | FRCP Rule | Purpose |
|------|-----------|---------|
| Interrogatories | 33 | Written questions (25 max without leave) |
| Document Requests | 34 | Request to produce documents/ESI |
| Requests for Admission | 36 | Admit or deny facts/genuineness of documents |
| Depositions | 30-31 | Oral or written examination of witnesses |
| Physical/Mental Exams | 35 | Condition in controversy — good cause required |

### ESI Discovery (FRCP 37(e))
- Duty to preserve when litigation is reasonably anticipated (*Zubulake v. UBS Warburg*, 220 F.R.D. 212 (S.D.N.Y. 2003))
- Meet and confer on ESI format (FRCP 26(f))
- Privilege log for withheld documents (FRCP 26(b)(5))
- Safe harbor for good-faith, routine deletion (FRCP 37(e))
- Adverse inference for spoliation (*Pension Committee v. Banc of America Securities*, 685 F. Supp. 2d 456 (S.D.N.Y. 2010))

## Common Discovery Motions
- Motion to Compel (FRCP 37(a)) — Certify good-faith conference required
- Motion for Protective Order (FRCP 26(c)) — Good cause required
- Motion for Sanctions (FRCP 37(b)-(f))

## ContextCut Prompts
- "Draft interrogatories for a [claim type] case focusing on [topic]"
- "Draft a document request for [specific documents] in a [case type]"
- "Respond to this discovery request with appropriate objections: [request text]"
"""

files["lawyer-lit-MOTIONS.md"] = """# Motion Practice

## Motion Categories

### Dispositive Motions
| Motion | Standard | Rule |
|--------|----------|------|
| Summary Judgment | No genuine dispute of material fact | FRCP 56 |
| Judgment on Pleadings | No material facts in dispute | FRCP 12(c) |
| Dismissal | Failure to state a claim | FRCP 12(b)(6) |
| Involuntary Dismissal | Plaintiff failed to prosecute | FRCP 41(b) |

### Nondispositive Motions
- Motion to Compel (FRCP 37(a))
- Motion for Protective Order (FRCP 26(c))
- Motion in Limine
- Motion to Extend Time (FRCP 6(b))
- Motion for Leave to Amend (FRCP 15(a))
- Motion to Seal

### Summary Judgment Standard (FRCP 56)
- **Burden**: Movant shows no genuine dispute of material fact
- **Shifting Burden**: *Celotex Corp. v. Catrett*, 477 U.S. 317 (1986)
- **Evidence**: Must be admissible at trial (*Scott v. Harris*, 550 U.S. 372 (2007))
- **Inferences**: Drawn in favor of non-movant (*Anderson v. Liberty Lobby*, 477 U.S. 242 (1986))

## Motion Drafting Structure
1. **Caption** — Court, case number, judge, title
2. **Notice of Motion** — Date, time, relief sought
3. **Memorandum of Law** — Statement of facts, legal argument, conclusion
4. **Supporting Documents** — Affidavits, exhibits, declarations
5. **Proposed Order** — Clean and redline versions

## Local Rules
Always consult local court rules for:
- Page limits
- Formatting requirements
- Courtesy copies
- Oral argument practices
- Submission procedures (ECF vs. paper)

## ContextCut Prompts
- "Draft a motion for summary judgment based on the following facts and legal standard: [facts/standard]"
- "Draft a response to a motion to dismiss under FRCP 12(b)(6) for [claim type]"
- "What are the elements of a prima facie case for [claim type] under [state] law?"
"""

files["lawyer-lit-EVIDENCE.md"] = """# Evidence Practice

## Federal Rules of Evidence

### Article IV — Relevance
- **401**: Relevant if it has any tendency to make a fact more/less probable
- **402**: Relevant evidence admissible; irrelevant inadmissible
- **403**: Exclusion if unfair prejudice substantially outweighs probative value

### Article V — Privileges
- **501**: Common law privileges — attorney-client, spousal, psychotherapist-patient (*Jaffee v. Redmond*, 518 U.S. 1 (1996))
- **Work Product**: *Hickman v. Taylor*, 329 U.S. 495 (1947); FRCP 26(b)(3)

### Article VI — Witnesses
- **601**: Competency to testify
- **602**: Personal knowledge required
- **607**: Any party may impeach a witness
- **608**: Character for truthfulness — opinion/reputation evidence; specific instances
- **609**: Impeachment by prior criminal convictions
- **611**: Court control over examination
- **701**: Lay opinion — rationally based on perception
- **702**: Expert testimony — *Daubert* standard (*Daubert v. Merrell Dow Pharm.*, 509 U.S. 579 (1993))
- **703**: Bases of expert opinion — data reasonably relied upon
- **704**: Opinion on ultimate issue (except criminal mental state)
- **705**: Disclosure of underlying facts

### Article VIII — Hearsay
- **801**: Definitions — statement, declarant, hearsay (prior statements by testifying witness, opposing party statements are NON-hearsay)
- **802**: Hearsay not admissible except as provided
- **803**: Exceptions — declarant availability immaterial (business records, public records, present sense impression, excited utterance, then-existing state of mind)
- **804**: Exceptions — declarant unavailable (former testimony, dying declaration, statement against interest)
- **805**: Hearsay within hearsay
- **807**: Residual exception

### Article IX — Authentication
- **901**: Evidence sufficient to support a finding that the matter is what it's claimed to be
- **902**: Self-authenticating documents (certified copies, public records, commercial paper)

### Article X — Best Evidence
- **1002**: Original required to prove content
- **1003**: Duplicate admissible unless genuine question raised
- **1004**: Original not required (lost/destroyed, not obtainable, opponent possesses)

## ContextCut Prompts
- "Does this evidence satisfy the business records exception under FRE 803(6)? [evidence description]"
- "Prepare a Daubert challenge to expert testimony on [subject]"
- "Is this statement hearsay? Analyze under FRE 801-807: [statement and context]"
"""

files["lawyer-lit-APPEAL.md"] = """# Appellate Practice

## Federal Appellate Procedure

### Notice of Appeal (FRAP 3, 4)
- **Civil**: 30 days after judgment entered (FRAP 4(a)(1)(A))
- **Criminal**: 14 days (FRAP 4(b)(1)(A))
- **Government** (criminal): 30 days (FRAP 4(b)(1)(B))
- **Tolling Motions**: FRAP 4(a)(4) — motions under FRCP 50(b), 52(b), 59 toll appeal time

### Standards of Review
| Issue | Standard | Key Case |
|-------|----------|----------|
| Questions of Law | De novo | *Salve Regina College v. Russell*, 499 U.S. 225 (1991) |
| Findings of Fact | Clear error | FRCP 52(a)(6) |
| Discretionary Decisions | Abuse of discretion | *Koon v. United States*, 518 U.S. 81 (1996) |
| Evidentiary Rulings | Abuse of discretion ('substantial prejudice' to overturn) | *Old Chief v. United States*, 519 U.S. 172 (1997) |
| Jury Verdicts | Sufficiency of evidence | *Jackson v. Virginia*, 443 U.S. 307 (1979) |

### Briefing (FRAP 28)
Required sections:
1. **Jurisdictional Statement** — Basis for appellate jurisdiction
2. **Statement of Issues** — Questions presented for review
3. **Statement of Case** — Nature of case, course of proceedings, disposition below
4. **Statement of Facts** — Supported by record citations
5. **Summary of Argument** — Concise overview
6. **Argument** — Contentions, reasons, authorities (w/ record references)
7. **Conclusion** — Specific relief sought

### Oral Argument (FRAP 34)
- Generally allowed unless panel unanimously agrees it's unnecessary
- Typically 15 minutes per side
- Reply time set in advance

### Key Strategies
- Preserve error below — contemporaneous objection (FRE 103(a))
- Identify the standard of review in the first sentence of each argument section
- Cite the record for every factual assertion
- Address unfavorable authority directly
- Focus on the most reversible error (don't dilute with weaker arguments)

## ContextCut Prompts
- "Draft an appellate brief arguing that the district court erred in [specific ruling]"
- "What is the standard of review for [specific issue], and how does it affect our argument?"
- "Identify all preserved errors from this trial record for appeal: [record summary]"
"""

# ═══════════════════════════════════════════════════════════════
# LAWYER — REAL ESTATE
# ═══════════════════════════════════════════════════════════════

files["lawyer-re-PURCHASE.md"] = """# Real Estate Purchase and Sale Agreements

## Key Contract Provisions

### Essential Terms
- **Property Description**: Legal description (metes and bounds or lot/block), PIN
- **Purchase Price**: Amount, deposit structure, payment method
- **Closing Date**: Time is of the essence (typically)
- **Included/Excluded Personal Property**: Appliances, fixtures, chattels

### Due Diligence Period
- Inspection contingency (home, pest, radon, mold)
- Financing contingency (loan commitment deadline)
- Appraisal contingency (purchase price or appraised value, whichever is lower)
- Title review period (objections to title commitments)
- Survey review (encroachments, easements, boundary issues)

### Seller Disclosures
- **Property Condition Disclosure** (state-specific — some states are "caveat emptor," others require disclosure)
- **Lead-Based Paint** (Residential Lead-Based Paint Hazard Reduction Act, 42 U.S.C. §4852d — pre-1978)
- **Seller's Property Disclosure Statement** (varies by state)
- **Material Defects**: *Stambovsky v. Ackley*, 572 N.Y.S.2d 672 (App. Div. 1991) — duty to disclose known defects

### Closing Conditions
- Title policy (owner's and/or lender's)
- Survey certification
- Homeowner's insurance
- Clear title (no undisclosed liens or encumbrances)
- Compliance with all contingencies

## ContextCut Prompts
- "Review this residential purchase agreement [clause/type] and identify standard vs. problematic provisions"
- "Draft an addendum addressing [specific issue] for a real estate purchase contract under [state] law"
- "What disclosures are required under [state] law for the sale of a residential property built in [year]?"
"""

files["lawyer-re-LEASE.md"] = """# Commercial and Residential Leases

## Commercial Lease Types
- **Gross Lease**: Landlord pays all operating expenses
- **Net Lease**: Tenant pays proportional share of expenses
  - Single Net (N): Tenant pays property taxes
  - Double Net (NN): Tenant pays taxes + insurance
  - Triple Net (NNN): Tenant pays taxes, insurance, maintenance
- **Percentage Lease**: Base rent + percentage of gross sales
- **Ground Lease**: Tenant leases land, owns improvements

## Key Commercial Lease Provisions
- **Use Clause**: Permitted use; exclusivity; radius restrictions
- **Assignment/Subletting**: Consent not unreasonably withheld (Res. 2d of Prop. §15.2(2))
- **CAM Charges**: Common Area Maintenance — caps, audit rights, capitalization
- **Tenant Improvements**: Allowance, ownership at termination, depreciation
- **Go Dark Clause**: Tenant's right to cease operations
- **Options**: Renewal, expansion, right of first refusal
- **Estoppel Certificate**: Tenant's confirmation of lease terms (required for landlord financing)

## Residential Lease Considerations
- **Implied Warranty of Habitability**: *Javins v. First National Realty Corp.*, 428 F.2d 1071 (D.C. Cir. 1970) — applies to all residential leases
- **Security Deposits**: Maximum limits, interest requirements, return timeline (state-specific)
- **Retaliatory Eviction**: Prohibited where tenant exercises legal rights (state-specific)
- **Rent Control**: Varies by municipality (NYC, San Francisco, Los Angeles, etc.)

## Landlord-Tenant Disputes
- **Eviction Process**: Notice requirements, cure periods, summary proceedings
- **Rent Withholding**: Conditions and procedures (must follow statutory requirements)
- **Constructive Eviction**: Landlord action renders premises uninhabitable — tenant must vacate

## ContextCut Prompts
- "Draft a NNN commercial lease for [property type] under [state] law with [key terms]"
- "Review this CAM clause for tenant-favorable vs. landlord-favorable provisions: [clause text]"
- "Analyze this residential lease for compliance with [state] landlord-tenant law"
"""

files["lawyer-re-TITLE.md"] = """# Title Insurance and Examination

## Title Examination Process
1. **Chain of Title**: Trace ownership back to root of title (typically 30-60 years)
2. **Current Owner**: Verify vesting deed and legal description
3. **Encumbrances**: Mortgages, liens, easements, restrictions, covenants
4. **Judgment/ Tax Lien Search**: Federal, state, county records
5. **UCC Search**: Fixture filings, financing statements
6. **Probate**: Verify authority of personal representative/heirs
7. **Tax Status**: Current and delinquent property taxes

## Title Commitments (ALTA / CLTA Forms)
- **Schedule A**: Policy amount, insured parties, legal description, estate, exceptions
- **Schedule B-I**: Standard exceptions (typically deleted for lender's policy)
- **Schedule B-II**: Specific exceptions (defects found in examination)

## Title Insurance Policies
- **Owner's Policy**: Protects buyer's equity (amount = purchase price)
- **Lender's Policy**: Protects lender (amount = loan balance)
- **Coverage**: Forgery, undisclosed heirs, improper recording, encroachments (covered)
- **Exclusions**: Zoning, governmental regulations, eminent domain; matters created by insured; matters known to insured but not disclosed

## Common Title Issues
- **Wild Deeds**: Conveyance from someone not in chain of title
- **Gap in Chain**: Missing transfer in recorded chain
- **Forged Documents**: Not covered by general warranty deed's warranty
- **Adverse Possession**: Open, notorious, continuous, hostile, exclusive — statutory period (varies 5-30 yrs)
- **Mechanic's Liens**: Claimant not paid for improvements — priority rules (varies by state)

## ContextCut Prompts
- "Review this title commitment and identify all Schedule B-II exceptions that should be cleared"
- "Draft an objection letter to the title company regarding [specific title issue]"
- "Analyze whether this potential adverse possession claim has merit under [state] law: [facts]"
"""

files["lawyer-re-ZONING.md"] = """# Zoning and Land Use

## Zoning Classifications
- **Residential**: R-1 (single-family), R-2 (multi-family), R-3 (high-density)
- **Commercial**: C-1 (neighborhood), C-2 (general), C-3 (regional)
- **Industrial**: I-1 (light), I-2 (heavy), I-3 (special)
- **Mixed-Use**: MXU, PUD (Planned Unit Development) * See *Village of Euclid v. Ambler Realty Co.*, 272 U.S. 365 (1926) — constitutional validity of zoning

## Land Use Approvals

### Special Use Permits
Uses that are generally compatible but require individual review (e.g., churches, schools, daycares in residential zones)

### Variances
- **Use Variance**: Permits a prohibited use (higher standard)
- **Area Variance**: Relaxes dimensional requirements (lower standard)
- **Undue Hardship**: Unique property characteristics, no reasonable return, not self-created—*Nettleton v. Zoning Board*, 828 A.2d 135 (Conn. 2003)

### Planned Unit Development (PUD)
Flexible zoning for large-scale development — allows mixed uses, varied densities, open space

### Subdivision Approval
Division of a tract into lots — requires:
- Plat approval
- Infrastructure improvements
- Dedications for roads, parks, utilities
- Compliance with subdivision regulations

## Environmental Considerations
- **NEPA**: Environmental impact statements for federal actions
- **CERCLA** (42 U.S.C. §9601): Liability for contaminated property
- **Phase I ESA**: ASTM E1527-21 standard — all appropriate inquiries
- **Wetlands**: Clean Water Act §404 — Army Corps of Engineers jurisdiction (*Rapanos v. United States*, 547 U.S. 715 (2006))

## Constitutional Issues
- **Fifth Amendment Takings**: *Penn Central Transportation Co. v. City of New York*, 438 U.S. 104 (1978) — economic impact, investment-backed expectations, character of government action
- **Regulatory Takings**: *Lucas v. South Carolina Coastal Council*, 505 U.S. 1003 (1992) — total economic wipeout
- **First Amendment**: Sign ordinances, adult uses (*City of Renton v. Playtime Theatres*, 475 U.S. 41 (1986))

## ContextCut Prompts
- "Analyze whether this proposed use is permitted under the [municipality] zoning code: [use description, zone]"
- "Draft an application for a variance from the [specific requirement] of the [municipality] zoning ordinance"
- "What environmental due diligence is required before acquiring [property type] property that was formerly [prior use]?"
"""

files["lawyer-re-CLOSING.md"] = """# Real Estate Closing Procedures

## Pre-Closing Checklist
- [ ] Title commitment received and reviewed
- [ ] Survey ordered and reviewed
- [ ] Loan commitment issued (if applicable)
- [ ] Homeowner's insurance binder obtained
- [ ] Termite inspection completed
- [ ] Final walk-through completed
- [ ] HOA estoppel certificate obtained (if applicable)
- [ ] Closing Disclosure reviewed (3 days before — TILA-RESPA, 12 CFR §1026.19)
- [ ] Fund transfer instructions confirmed
- [ ] Recording instructions prepared

## Closing Documents

### Buyer Documents
- Promissory Note (if financing)
- Deed of Trust / Mortgage
- Closing Disclosure
- Borrower's Affidavit
- Occupancy Affidavit (if owner-occupied)
- IRS Form W-9
- 1031 Exchange documents (if applicable)

### Seller Documents
- Warranty / Special Warranty / Quitclaim Deed
- Bill of Sale (personal property)
- Affidavit of Title
- FIRPTA Affidavit (Foreign Investment in Real Property Tax Act, IRC §1445)
- 1099-S (if required)
- Property Condition Disclosure

### Escrow/Closing
- Settlement Statement (ALTA/ HUD-1 or Closing Disclosure)
- Prorations (taxes, HOA dues, rents, utilities)
- Recording fees and transfer taxes
- Commission instructions

## Post-Closing
- Record deed and mortgage
- Disburse funds per settlement statement
- File declarations of homestead (where applicable)
- Issue title policies (owners and lenders)
- Transfer utility accounts
- Notify HOA of ownership change

## ContextCut Prompts
- "Draft a closing checklist for a [residential/commercial] transaction in [state]"
- "Review this Closing Disclosure for TRID compliance issues: [CD details]"
- "Calculate the tax prorations for a closing on [date] with annual taxes of $[amount]"
"""

# ═══════════════════════════════════════════════════════════════
# CPA — PERSONAL
# ═══════════════════════════════════════════════════════════════

files["cpa-personal-INCOME.md"] = """# Individual Income Taxation

## Gross Income (IRC §61)
"Except as otherwise provided, gross income means all income from whatever source derived."

### Types of Income
- **Compensation for services**: Wages, salaries, fees, commissions, bonuses (IRC §61(a)(1))
- **Business income**: Gross income from business (IRC §61(a)(2); Schedule C)
- **Investment income**: Interest (IRC §61(a)(4)), dividends (IRC §61(a)(7)), capital gains (IRC §61(a)(3))
- **Rents and royalties**: IRC §61(a)(5)
- **Pensions and annuities**: IRC §61(a)(11)
- **Discharge of indebtedness**: IRC §61(a)(12); exclusions under IRC §108
- **Alimony**: Only for pre-2019 divorces (TCJA eliminated alimony deduction/ inclusion for post-2018 agreements)

### Exclusions from Gross Income (Partial List)
- **Gifts and inheritances**: IRC §102
- **Life insurance proceeds**: IRC §101 (exceptions for transfer for value)
- **Qualified scholarships**: IRC §117
- **Municipal bond interest**: IRC §103
- **Compensatory damages for physical injury**: IRC §104(a)(2)
- **Employer-provided health insurance**: IRC §106
- **Fringe benefits**: IRC §132 (de minimis, no-additional-cost, qualified employee discounts)
- **Foreign earned income exclusion**: IRC §911 (up to $120,000 for 2023, indexed)

## Tax Rate Schedules (IRC §1)
Current brackets: 10%, 12%, 22%, 24%, 32%, 35%, 37% — indexed annually for inflation

## Filing Status (IRC §1-2, 7703)
- Single
- Married Filing Jointly (MFJ)
- Married Filing Separately (MFS)
- Head of Household (HoH)
- Qualifying Surviving Spouse (QSS)

## ContextCut Prompts
- "Calculate the tax liability for a single filer with $[wage income], $[investment income], and $[business income] for [tax year]"
- "Is this [income type] includible in gross income under IRC §61 or excluded under [specific exclusion]?"
- "What filing status options are available for a taxpayer who [marital status facts]?"
"""

files["cpa-personal-DEDUCTION.md"] = """# Itemized Deductions

## Standard Deduction (IRC §63)
For 2024: Single $14,600; MFJ $29,200; HoH $21,900; QSS $29,200; MFS $14,600
Additional for age 65+/ blind: $1,550 (single/HoH), $1,250 (MFJ/MFS/QSS)

## Itemized Deductions (Schedule A)

### Medical and Dental (IRC §213)
- Deductible to extent >7.5% of AGI (TCJA permanently set at 7.5% for 2020+)
- Qualified: Diagnosis, cure, mitigation, treatment, prevention
- Includes: Insurance premiums, prescription drugs, hospital services, travel (18¢/mi for 2024)
- Excludes: Cosmetic surgery (unless medical necessity), over-the-counter drugs (without prescription — exception for insulin)

### State and Local Taxes (SALT — IRC §164)
- **Cap**: $10,000 ($5,000 MFS) — TCJA limitation (Pub. L. 115-97)
- Includes: State income/sales tax (choose one), real property tax, personal property tax
- Does NOT include: Federal taxes, estate/inheritance/gift taxes, gasoline taxes

### Home Mortgage Interest (IRC §163(h))
- **Acquisition Indebtedness**: Interest on ≤$750,000 ($375,000 MFS) for post-12/15/17 debt ($1M/$500K for pre-existing)
- **Home Equity Debt**: Interest deductible only if used to buy, build, or substantially improve the home (post-TCJA)
- **Points**: Generally amortized over loan term (exception for purchase-money mortgages)

### Charitable Contributions (IRC §170)
- **Public Charities**: Up to 60% of AGI (cash), 30% (property), 20% (capital gain property)
- **Private Foundations**: More restrictive limits
- **Qualified Organizations**: 501(c)(3) — verify with IRS Tax Exempt Organization Search
- **Substantiation**: Cash ≥$250 — contemporaneous written acknowledgment; non-cash >$500 — Form 8283; >$5,000 — qualified appraisal

### Casualty and Theft Losses (IRC §165)
- Limited to federally declared disaster areas (post-TCJA through 2025)
- Deductible to extent >10% of AGI after $100 per event (for personal-use property)

## Tax Cuts and Jobs Act (TCJA) Sunset
Most TCJA provisions expire after 2025, including:
- Lower rates and expanded brackets
- Increased standard deduction
- SALT cap
- Mortgage interest limit ($750,000)
- Charitable contribution AGI limits (60%)
- Miscellaneous itemized deductions (2% floor — suspended through 2025)

## ContextCut Prompts
- "Calculate whether this taxpayer should itemize or take the standard deduction for [tax year] given: [income/deduction facts]"
- "Is this [expense type] deductible as a medical expense under IRC §213? [expense description]"
- "Determine the deductible mortgage interest for a taxpayer with [acquisition debt amount] at [interest rate]%"```

## Standard Deduction vs. Itemizing
- Itemize if > standard deduction
- Medical > 7.5% of AGI
- State/local taxes (SALT) capped at $10k
- Mortgage interest on ≤$750k acquisition debt
- Charitable contributions to 501(c)(3)
- Casualty losses (federally declared disasters only)
"""

files["cpa-personal-INVESTMENT.md"] = """# Investment Income and Losses

## Capital Assets and Basis

### Basis Determination (IRC §1011-1016)
- **Cost Basis**: Purchase price + commissions + improvements
- **Adjusted Basis**: Cost basis — depreciation / + improvements
- **Gifted Property**: Carryover basis (donee takes donor's basis — IRC §1015)
- **Inherited Property**: Step-up to FMV at decedent's death (IRC §1014)
- **Like-Kind Exchange**: Carryover basis (IRC §1031 — real property only post-TCJA)

### Capital Gains and Losses (IRC §1201-1223, §1001)
| Holding Period | Rate (2024) | Characterization |
|----------------|-------------|------------------|
| ≤1 year | Ordinary rates | Short-term capital gain |
| >1 year | 0/15/20%* | Long-term capital gain |

* Plus 3.8% Net Investment Income Tax (NIIT — IRC §1411) for taxpayers with AGI >$200K/$250K

## Capital Loss Limitations (IRC §1211-1212)
- **Net capital loss**: Limited to $3,000/year ($1,500 MFS) against ordinary income
- **Carryforward**: Indefinitely (IRC §1212(b))
- **Wash Sale Rule**: IRC §1091 — loss disallowed if substantially identical security acquired within 30 days before/after sale

## Dividend Taxation
- **Qualified Dividends**: Taxed at capital gains rates (must meet holding period — IRC §1(h)(11))
- **Ordinary Dividends**: Taxed at ordinary rates
- **Dividend Received Deduction (DRD)** — IRC §243: Corporate shareholders deduct 50-100% of dividends received

## Passive Activity Losses (IRC §469)
- **Passive Activity**: Trade/business in which taxpayer does not materially participate
- **Rental Activities**: Presumptively passive (with exceptions for real estate professionals — IRC §469(c)(7))
- **Suspended Losses**: Carried forward until full disposition of activity
- **Passive vs. Active**: Material participation = 500+ hours/year or substantially all participation

## Net Investment Income Tax (NIIT — IRC §1411)
- 3.8% on lesser of net investment income or MAGI exceeding threshold
- Thresholds: $250K MFJ/QSS, $125K MFS, $200K single/HoH
- Includes: Interest, dividends, capital gains, rental income, pass-through income (unless active)

## ContextCut Prompts
- "Calculate the tax impact of selling [stock/shares] acquired on [date] with basis of $[basis] for $[sale price]"
- "Does the wash sale rule apply to this transaction: [transaction details]?"
- "Determine whether this [activity] is passive or active under IRC §469: [facts]"
"""

files["cpa-personal-ESTATE.md"] = """# Estate and Gift Tax

## Federal Estate Tax (IRC §2001-2210)

### Estate Tax Computation
1. **Gross Estate** (IRC §2031-2046): All property owned at death
2. **Deductions** (IRC §2051-2056): Marital, charitable, debts, expenses, losses
3. **Adjusted Gross Estate**: Gross estate minus deductions
4. **Taxable Estate**: Adjusted gross estate minus specific exemption
5. **Tentative Tax**: Apply rate schedule
6. **Credits**: Unified credit, state death tax, foreign death tax, prior transfers

### Applicable Exclusion Amount
- **2024**: $13,610,000 per person ($27,220,000 MFJ — portability under IRC §2010(c))
- **2025**: $13,990,000 per person (indexed for inflation)
- **2026 Sunset**: Returns to ~$5M indexed (pre-TCJA level) unless Congress acts

### Marital Deduction (IRC §2056)
Unlimited deduction for property passing to surviving spouse (US citizen)
- QTIP Trust (IRC §2056(b)(7)): Qualified Terminable Interest Property — allows marital deduction with controlled disposition
- QDOT (IRC §2056A): Qualified Domestic Trust — needed if surviving spouse is non-US citizen

### Portability (IRC §2010(c))
Unused exclusion amount transfers to surviving spouse — must file Form 706 within 9 months of death (+ 6-month extension)

## Federal Gift Tax (IRC §2501-2524)

### Annual Exclusion (IRC §2503(b))
- **2024**: $18,000 per donee (indexed)
- **2025**: $19,000 per donee
- Unlimited number of donees
- Covers present interests only (Crummey powers for trusts — *Crummey v. Commissioner*, 397 F.2d 82 (9th Cir. 1968))

### Lifetime Exemption (IRC §2505)
Unified with estate tax — total $13.61M (2024)

## Generation-Skipping Transfer Tax (GSTT — IRC §2601-2664)
- Flat rate = highest estate tax rate (40%)
- $13.61M exemption per person (2024), same as estate tax
- Applies to transfers to beneficiaries 2+ generations younger

## State Estate/Inheritance Taxes
- **Estate Tax States**: ~12 states + DC (exemptions vary, many under $5M)
- **Inheritance Tax States**: ~6 states (tax based on relationship to decedent)

## ContextCut Prompts
- "Calculate federal estate tax for a decedent with gross estate of $[amount], debts of $[amount], and bequests of $[amount] to spouse"
- "Is this transfer subject to gift tax? Calculate available annual exclusion and lifetime exemption usage: [facts]"
- "Draft an estate plan checklist for a married couple with $[total net worth], including [specific goals]"
"""

files["cpa-personal-RETIREMENT.md"] = """# Retirement Planning

## Retirement Account Types

### Traditional IRA (IRC §408)
- **Contribution (2024)**: $7,000 ($8,000 if age 50+) — fully deductible if not covered by employer plan
- **Income Limits (deductibility)**: Deduction phases out with MAGI (depends on filing status and employer coverage)
- **Taxation**: Deductible contributions → fully taxable on withdrawal
- **RMDs**: Required beginning April 1 after age 73 (SECURE 2.0, §107)
- **Roth Conversion**: IRC §408A(d)(3) — taxable event; no income limit for conversions

### Roth IRA (IRC §408A)
- **Contribution (same limits)**: $7,000 ($8,000 age 50+)
- **Income Limits (contribution)**: Phaseouts: MFJ $230-240K, Single $146-161K (2024)
- **Qualified Distributions**: Tax-free if account ≥5 years old AND age 59½, death, disability, or first-time home ($10K)
- **No RMDs**: SECURE 2.0 eliminated Roth RMDs effective 2024

### 401(k) Plans (IRC §401(k))
- **Elective Deferral (2024)**: $23,000 (+ $7,500 catch-up age 50+)
- **Employer Match**: Discretionary; typically 50-100% up to certain percentage
- **Roth 401(k)**: After-tax contributions with tax-free qualified distributions
- **SECURE 2.0 Changes**: Higher catch-up for ages 60-63 ($10,000+ in 2025); mandatory auto-enrollment for new plans (2025)

### SEP IRA (IRC §408(k))
- **Contribution**: Up to 25% of compensation or $69,000 (2024), whichever is less
- **For self-employed**: 20% of net self-employment income
- **Simple**: Minimal administration; employer must contribute

### Solo 401(k)
- For self-employed individuals with no employees (or spouse only)
- **Employee Deferral**: Same as 401(k) limits
- **Employer Contribution**: Up to 25% of compensation
- **Total**: Up to $69,000 (2024) + $7,500 catch-up

## Saver's Credit (IRC §25B)
- **Credit Rate**: 50%, 20%, or 10% of contributions (up to $2,000/$4,000 joint)
- **Income Limits (2024)**: MFJ $76,500; HoH $57,375; Single/MFS $38,250

## ContextCut Prompts
- "Calculate the maximum retirement contribution for a self-employed individual with net earnings of $[amount] in [year]"
- "Compare the tax impact of Traditional 401(k) vs. Roth 401(k) contributions for a taxpayer in the [bracket]% bracket"
- "Determine RMD for a taxpayer age [age] with IRA balance of $[amount] (use IRS Uniform Lifetime Table)"
"""

# ═══════════════════════════════════════════════════════════════
# CPA — SMALL BUSINESS
# ═══════════════════════════════════════════════════════════════

files["cpa-smb-ENTITY.md"] = """# Business Entity Taxation

## Entity Tax Comparison

| Aspect | Sole Proprietorship | Partnership | LLC (Sole/Multi) | S-Corp | C-Corp |
|--------|-------------------|-------------|-------------------|--------|--------|
| Tax Filing | Schedule C | Form 1065 | Same as underlying | Form 1120-S | Form 1120 |
| SE Tax | All net income | On distributive share (if active) | Same as partnership/sole prop | Reasonable salary only | N/A |
| QBI (199A) | Eligible | Eligible | Eligible | Eligible (wage/capital limit) | Not eligible |
| Double Tax | No | No | No | No | Yes |
| Fringe Benefits | Not deductible to self-partner | Not to >2% S-shareholder | Deductible to corp, taxable to employee |

### C-Corp Double Taxation
1. Corporate-level tax (IRC §11 — 21% flat post-TCJA)
2. Shareholder-level tax on dividends (qualified rate 0/15/20%)

### S-Corp Election (IRC §1361-1362)
- Requirements: US corporation, ≤100 shareholders, one class of stock, eligible shareholders (individuals, estates, certain trusts — IRC §1361(b))
- Election: Form 2553 by 15th day of 2nd month of tax year (IRC §1362(b)(1))
- Termination: Revocation, new disqualifying shareholder, passive investment income >25% for 3 yrs (S-Corp with C-Corp E&P — IRC §1362(d))

### LLC Tax Classification (Check-the-Box — Treas. Reg. §301.7701-3)
- Single-member: Default = disregarded entity (Schedule C)
- Multi-member: Default = partnership (Form 1065)
- Election available: Form 8832 to elect C-Corp or S-Corp status

## ContextCut Prompts
- "Compare the tax impact of operating as an S-Corp vs. LLC for a [profession] earning $[amount]"
- "Calculate self-employment tax for a sole proprietor with net income of $[amount]"
- "Should this business elect S-Corp status? Analyze based on [facts]"
"""

files["cpa-smb-BOOKS.md"] = """# Bookkeeping and Accounting Methods

## Accounting Methods
- **Cash Method**: Income when received; expenses when paid (IRC §446(c))
- **Accrual Method**: Income when earned; expenses when incurred (IRC §446(c))
- **Hybrid Method**: Combination (with IRS approval — IRC §446(c)(4))
- **Small Business Exception**: Cash method available if average gross receipts ≤$30M (2024; indexed) — TCJA §13112

## Accounting Methods for Tax
- **UNICAP (IRC §263A)**: Uniform Capitalization — manufacturers/retailers with gross receipts >$30M must capitalize direct/indirect costs
- **Section 263A Safe Harbor**: Small taxpayers (gross receipts ≤$30M) — exempt from UNICAP (Rev. Proc. 2018-48)

## Key Bookkeeping Concepts
- **Chart of Accounts**: Assets, Liabilities, Equity, Revenue, Expenses
- **Double-Entry System**: Every transaction affects ≥2 accounts (debits = credits)
- **GAAP vs. Tax Basis**: Differences in timing, valuation, recognition
  - GAAP: Revenue recognized when earned (ASC 606)
  - Tax: All events test for accrual (IRC §451; Treas. Reg. §1.451-1(a))

## Recordkeeping Requirements
- **Tax Returns**: 3 years from filing date (generally for audit statute — IRC §6501)
- **Employment Tax Records**: 4 years (IRC §6501)
- **Asset Records**: Life of asset + 3 years after disposal
- **Statute of Limitations**: Generally 3 years; 6 years for substantial omission (>25% of gross income — IRC §6501(e)); no limit for fraud (IRC §6501(c))
- **Electronic Records**: Must be retained in machine-readable format (Rev. Proc. 98-25)

## Common Bookkeeping Errors
- Personal/Business expense commingling
- Improper capitalization of expenses (IRC §263(a) vs. IRC §162)
- Failure to reconcile bank accounts monthly
- Incorrect payroll tax accruals
- Missing 1099 information for contractors

## ContextCut Prompts
- "Set up a chart of accounts for a [industry] business"
- "Classify this expense as capitalizable (IRC §263A) or currently deductible (IRC §162): [expense description]"
- "Prepare a list of all accounts that must be reconciled monthly for a small business"
"""

files["cpa-smb-PAYROLL.md"] = """# Payroll Tax Compliance

## Employment Taxes

### Employer Responsibilities
1. **Withholding**: Income tax (per W-4), FICA (Social Security 6.2% + Medicare 1.45%)
2. **Employer Share**: FICA matching (6.2% + 1.45%) + FUTA (6% on first $7,000, offset by SUTA credit)
3. **Remittance**: Semi-weekly or monthly deposit schedule (based on lookback period — IRC §6302; Treas. Reg. §31.6302-1)
4. **Reporting**: Form 941 (quarterly), Form 940 (annual), Form W-2 (annual), state equivalents

### Worker Classification
**Employee vs. Independent Contractor**:
- **Common Law Test**: Behavioral control, financial control, relationship (Treas. Reg. §31.3401(c)-1)
- **Section 530 Relief**: Safe harbor if consistent treatment + reasonable basis (Revenue Act of 1978 §530)
- **Worker Classification**: Form SS-8 determination by IRS; Form 8919 for misclassified workers who paid higher SECA
- **Penalties for Misclassification**: Back taxes, penalties (IRC §6656 for failure to deposit), interest

### Payroll Tax Deposit Penalties (IRC §6656)
| Days Late | Penalty |
|-----------|---------|
| 1-5 days | 2% |
| 6-15 days | 5% |
| 16+ days | 10% |
| >10 days after first notice | 15% |
| Trust fund recovery penalty (TFRP — IRC §6672) | 100% of withheld taxes |

### Payroll Tax Returns
- **Form 941**: Quarterly — due Apr 30, Jul 31, Oct 31, Jan 31
- **Form 940**: Annual — due Jan 31
- **Form W-2**: To employees by Jan 31; to SSA by Jan 31 (paper) or Apr 1 (e-file)
- **Form 1099-NEC**: To contractors by Jan 31; to IRS by Jan 31 (IRC §6041)
- **State**: Varies; most require quarterly wage and unemployment reports

## ContextCut Prompts
- "Classify this worker as employee or independent contractor using the common law test: [worker facts]"
- "Calculate payroll tax deposit due for a semi-weekly depositor with payroll of $[amount] on [date]"
- "What is the total employer cost (payroll taxes + benefits) for an employee earning $[salary]?"
"""

files["cpa-smb-QBI.md"] = """# Qualified Business Income Deduction (IRC §199A)

## Overview
Pass-through deduction allowing up to 20% of qualified business income (QBI) from sole proprietorships, partnerships, S-Corps, and trusts/estates.

## Basic Computation
QBI Deduction = Lesser of:
1. 20% of QBI, or
2. 20% of taxable income minus net capital gain

## Specified Service Trade or Business (SSTB)
**Limitation phases in at threshold + $50K ($100K MFJ)**:
- SSTBs: Health, law, accounting, actuarial science, performing arts, consulting, athletics, financial/brokerage services, any business where goodwill from reputation/skill is a factor (Treas. Reg. §1.199A-5(b)(2)(xiv))
- NOT SSTB: Architects, engineers (since 2018 — Tax Technical Corrections Act)

## Wage/Capital Limitations (Treas. Reg. §1.199A-2)
**For QBI above threshold ($191,950 single/$383,900 MFJ for 2024)**:
Deduction limited to greater of:
1. 50% of allocable W-2 wages from the qualified trade or business, or
2. 25% of W-2 wages + 2.5% of unadjusted basis of qualified property (UBIA)

## Thresholds (2024)
| Filing Status | Threshold | Phase-In Range |
|---------------|-----------|----------------|
| Single/HoH | $191,950 | $191,950 - $241,950 |
| MFJ | $383,900 | $383,900 - $483,900 |
| MFS | $191,950 | $191,950 - $241,950 |

## Key Definitions (Treas. Reg. §1.199A-1)
- **QBI**: Net amount of qualified items of income, gain, deduction, and loss from qualified business — does NOT include reasonable compensation (S-Corp), guaranteed payments (partnership), or capital gains/losses (IRC §199A(c)(3))
- **Qualified Property**: Tangible property subject to depreciation and used in the business at year-end (IRC §199A(b)(6))
- **Aggregation**: Election available to treat multiple trades/businesses as one for QBI purposes (Treas. Reg. §1.199A-4)

## ContextCut Prompts
- "Calculate the IRC §199A QBI deduction for a single taxpayer with QBI of $[amount], W-2 wages of $[amount], and UBIA of $[amount]"
- "Is this business classified as an SSTB under §199A? [business description]"
- "Should this taxpayer aggregate their businesses for QBI purposes? Analyze: [business structures]"
"""

files["cpa-smb-SELFEMPLOYED.md"] = """# Self-Employment Tax

## Self-Employment Tax (IRC §1401-1403)

### Rate and Base
| Component | Rate | Wage Base (2024) |
|-----------|------|------------------|
| Social Security (OASDI) | 12.4% | $168,600 |
| Medicare (HI) | 2.9% | No limit |
| Additional Medicare | 0.9% | >$200K/$250K |
| **Total** | **15.3%** | See above |

### Net Earnings from Self-Employment (NESE — IRC §1402(a))
- **Gross Income**: From trade or business
- **Less**: Deductions attributable to business
- **× 92.35%**: Allowed (reflects the employer FICA deduction)
- **Less**: §1402(a)(12) deduction — reduces the SE tax base

### Who Must Pay
- Sole proprietors (Schedule C)
- Independent contractors
- Partners (general partner's distributive share — IRC §1402(a))
- LLC members (if active in business)
- S-Corp shareholders (do NOT pay SE tax—reasonable compensation required)

### SE Tax Deduction (IRC §164(f))
Above-the-line deduction for one-half of SE taxes paid — reduces both AGI and QBI computation

## Section 199A Interaction
QBI deduction includes SE tax deduction — be careful not to double count

## Estimated Tax (IRC §6654)
Must pay at least 90% of current year tax or 100% of prior year tax (110% if AGI >$150K) to avoid underpayment penalty

## Self-Employed Health Insurance Deduction (IRC §162(l))
Above-the-line deduction for health insurance premiums for self and dependents — cannot exceed net SE income

## Home Office Deduction (IRC §280A)
- **Exclusive and regular use** for business
- **Principal place of business**
- **Simplified method**: $5/sq ft up to 300 sq ft ($1,500 max)
- **Regular method**: Actual expenses × business use percentage

## Auto Expenses (IRC §162; Rev. Proc. 2019-46)
- **Standard Mileage Rate (2024)**: 67¢/mile business; 21¢/mile medical; 14¢/mile charitable
- **Actual Expense Method**: Depreciation (IRC §168), gas, insurance, repairs × business use %
- **Vehicle Options**: Section 179 (limited for luxury autos — IRC §280F), bonus depreciation

## ContextCut Prompts
- "Calculate self-employment tax for a sole proprietor with Schedule C net income of $[amount]"
- "Is the home office deduction available for this taxpayer under IRC §280A? [facts]"
- "Compare standard mileage vs. actual expense methods for a vehicle used [%] for business — which yields larger deduction?"
"""

# ═══════════════════════════════════════════════════════════════
# CPA — CORPORATE
# ═══════════════════════════════════════════════════════════════

files["cpa-corp-TAX.md"] = """# Corporate Taxation

## C-Corporation Tax (IRC §11)
**Flat rate**: 21% (post-TCJA, Pub. L. 115-97, effective 2018)
**Previous rates**: 15-35% graduated (pre-2018)

## Corporate Tax Formula
1. **Gross Income** (IRC §61) - ALL income from whatever source derived
2. **minus**: Deductions (IRC §162-§249, §261-§280H) = Taxable income
3. **× 21%** (IRC §11(b)) = Gross tax
4. **minus**: Credits (IRC §21-§53) = Net tax

## Key Corporate Deductions

### Dividends Received Deduction (DRD — IRC §243)
| Ownership % | DRD % |
|-------------|-------|
| <20% | 50% |
| 20-80% | 65% |
| >80% | 100% |

### Organizational Costs (IRC §248)
- Deduct up to $5,000 (phased out if costs >$50,000)
- Remaining costs amortized over 180 months

### Net Operating Losses (IRC §172 — Post-TCJA)
- NOL deduction limited to 80% of taxable income
- NOLs can only offset 80% of pre-NOL income
- NOL carryforward: Indefinite (post-2018)
- NOL carryback: Generally NOT allowed (exception for certain farming losses — IRC §172(b)(1)(F))

## Corporate AMT (IRC §55)
- Reinstated by IRA 2022 (Pub. L. 117-169)
- 15% on adjusted financial statement income (AFSI)
- Applies to corporations with 3-year average AFSI >$1 billion
- Effective for tax years beginning after 12/31/2022

## Corporate Estimated Taxes (IRC §6655)
Deposits required on 15th of 4th, 6th, 9th, 12th months of tax year
- Large corporations (>$1M taxable income in any of prior 3 years) — use prior year's tax × 100% for first quarter only

## S-Corp vs. C-Corp Decision Factors
- **Accumulated Earnings**: C-Corp retains at lower rate; eventual distributions taxed again
- **Losses**: S-Corp passes through; C-Corp trapped (except NOL)
- **Fringe Benefits**: C-Corp deducts; S-Corp owner ≥2% — treated as distributions
- **Fiscal Year**: C-Corp can adopt; S-Corp must use calendar year (absent business purpose — IRC §1378)

## ContextCut Prompts
- "Compute C-Corp tax liability for a corporation with $[revenue], $[expenses], and $[dividend income] received from a [%] owned subsidiary"
- "Should this business elect S-Corp status or remain a C-Corp? Analyze: [facts]"
- "Calculate corporate AMT under IRC §55 for a corporation with AFSI of $[amount]"
"""

files["cpa-corp-COMPLIANCE.md"] = """# Corporate Compliance and Reporting

## Federal Filing Requirements

### Form 1120 (C-Corp)
- **Due**: March 15 (calendar year); 15th day of 3rd month after year-end (fiscal year)
- **Extension**: Form 7004 — 6 months (due September 15)
- **State**: Varies; most follow federal due dates

### Form 1120-S (S-Corp)
- **Due**: March 15 (calendar year)
- **Extension**: Form 7004 — 6 months
- **Shareholder Schedules**: K-1 provided by March 15 (due date); extended to September 15

### Form 1065 (Partnership)
- **Due**: March 15
- **Extension**: 6 months
- **Partner Schedules**: K-1 provided by March 15

### Information Returns
- **Form 1099-NEC**: Nonemployee compensation — due January 31
- **Form 1099-MISC**: Other payments (rents, prizes, etc.) — due January 31
- **Form 1099-INT/DIV**: Interest/dividends — due February 28 (paper) or March 31 (e-file)
- **Form 1095-C**: Employer-provided health insurance (ACA requirement) — due March 31
- **FBAR (FinCEN Form 114)**: Foreign accounts >$10,000 — due April 15

## State Compliance
- **Income/Franchise Tax**: Nexus standards (Public Law 86-272 protection — interstate sales of tangible personal property only; *South Dakota v. Wayfair, Inc.*, 138 S. Ct. 2080 (2018) — economic nexus for sales tax)
- **Sales Tax**: Economic nexus thresholds (most states: $100K sales or 200 transactions)
- **Annual Reports**: Filed with Secretary of State (typically annual or biennial)
- **Foreign Qualification**: Must register in each state where business conducted

## Shareholder/Partner Reporting
- **K-1**: Reports pass-through income, deductions, credits
- **Basis Tracking**: Shareholder/partner must track basis annually (IRC §1367 for S-Corp; IRC §705 for partnership)
- **Distributions**: Tax-free to extent of basis; capital gain thereafter
- **At-Risk Rules (IRC §465)**: Losses limited to amount at risk
- **Passive Activity Rules (IRC §469)**: Losses limited to passive income (unless actively participating)

## IRS Audits
- **Correspondence Audit**: Most common; specific issue(s)
- **Office Audit**: In-person at IRS office
- **Field Audit**: At taxpayer's place of business
- **Appeals**: Independent Office of Appeals
- **Tax Court**: Prepayment forum — petition within 90 days of deficiency notice (90-day letter — IRC §6213)
- **DPAD**: District Court or Claims Court — pay first, sue for refund

## ContextCut Prompts
- "List all annual filing deadlines for a [entity type] with a [calendar/fiscal] year-end in [state]"
- "Determine the nexus/registration requirements for a [business type] selling [products] into [state]"
- "Track the S-Corp shareholder basis given: capital contribution $[amount], income $[amount], distributions $[amount], loans $[amount]"
"""

files["cpa-corp-MERGER.md"] = """# M&A Tax Considerations

## Deal Structure — Taxable vs. Tax-Free

### Taxable Transactions
- **Asset Sale**: Buyer gets stepped-up basis (IRC §1012); seller recognizes gain/(loss)
  - Double tax for C-Corp: Corporate + shareholder level
  - IRC §338(h)(10) election: Deemed asset sale for QSub/S-Corp
- **Stock Sale**: Buyer gets carryover basis; seller pays capital gains
  - C-Corp shareholder: capital gain (qualified rate)
  - Section 1202 (QSBS): Small business stock gain exclusion — up to 100% (IRC §1202)

### Tax-Free Reorganizations (IRC §368)
| Type | Description | Requirements |
|------|-------------|-------------|
| A | Statutory merger | State law merger + continuity of interest (Treas. Reg. §1.368-1(e)) |
| B | Stock-for-stock | Solely voting stock; ≥80% control (IRC §368(a)(1)(B)) |
| C | Stock-for-assets | Substantially all assets for voting stock (IRC §368(a)(1)(C)) |
| D | Divisive/reincorporation | Transfer to controlled corp (IRC §368(a)(1)(D)) |
| F | Name change | Mere change in identity |

### Continuity Requirements
- **Continuity of Business Enterprise**: Buyer must continue target's historic business or use significant assets (Treas. Reg. §1.368-1(d))
- **Continuity of Interest**: Target shareholders must retain equity in acquirer (Treas. Reg. §1.368-1(e))

## Tax Attributes (IRC §381-384)
- NOL carryforwards
- Basis
- E&P
- Credit carryovers
- **IRC §382 Limitation**: NOL usage limited after ownership change (annual limit = FMV × long-term tax-exempt rate)

## Key Provisions
- **IRC §351**: Tax-free incorporation transfer to controlled corporation
- **IRC §721**: Tax-free contribution to partnership
- **IRC §1031**: Like-kind exchange (real property only post-TCJA)
- **IRC §1035**: Exchange of insurance policies
- **IRC §1045**: Rollover of QSBS gain (60-day reinvestment)

## Due Diligence Checklist
- [ ] Tax returns — all open years
- [ ] NOL/credit carryforward schedules
- [ ] Transfer pricing documentation (IRC §482)
- [ ] State nexus and filing positions
- [ ] Sales/use tax compliance
- [ ] Payroll tax compliance
- [ ] Unrelated business income (if tax-exempt target)
- [ ] Tax controversy/examination history
- [ ] International operations (Subpart F, GILTI, FDII, BEAT)
- [ ] Section 382/383 studies

## ContextCut Prompts
- "Structure a tax-free acquisition of [target] by [acquirer] under IRC §368: [facts]"
- "Calculate the IRC §382 NOL limitation after an ownership change: pre-change FMV $[amount], tax-exempt rate [%]"
- "Analyze the tax attributes that carry over in a Type A reorganization under IRC §381"
"""

files["cpa-corp-INTL.md"] = """# International Tax

## US Taxation of Foreign Operations

### Worldwide vs. Territorial
US taxes worldwide income of US persons (IRC §61)
- **Foreign Tax Credit (IRC §901-909)**: Mitigates double taxation
- **Foreign Earned Income Exclusion (IRC §911)**: Up to $120,000 (2023) for qualified individuals

### Subpart F Income (IRC §951-965)
Current inclusion of certain income of Controlled Foreign Corporations (CFC — >50% owned by US shareholders)
- **Categories**: Foreign base company sales, services, personal holding company income, insurance, oil-related, shipping (IRC §952-954)
- **Exception**: High-tax exception (effective rate >90% of US rate — IRC §954(b)(4))
- **De Minimis**: If <5% of gross income and <$1M (IRC §954(b)(3)(A))

### GILTI (IRC §951A)
Global Intangible Low-Taxed Income — current inclusion of CFC income exceeding 10% of qualified business asset investment (QBAI)
- **Rate**: ~10.5% effective (50% deduction for GILTI — IRC §250)
- **FTC**: 80% of foreign taxes deemed paid (no carryover)
- **QBAI**: 10% of adjusted tax basis in depreciable tangible property

### FDII (IRC §250(b))
Foreign-Derived Intangible Income — deduction for US corporations' export-related intangible income
- **Rate**: ~13.125% effective (37.5% deduction for FDII — IRC §250(a)(1)(A)(i))
- **Sunset**: Rate decreases after 2025

### BEAT (IRC §59A)
Base Erosion and Anti-Abuse Tax — 10% minimum tax on large corporations (>$500M revenue) with excessive base erosion payments to foreign related parties
- **Rate**: 10% (2019-2025); 12.5% (2026+)

## Inbound Transactions
- **FDAP**: Fixed/Determinable/Periodic income — 30% withholding (IRC §871, §881; reduced by treaty)
- **ECI**: Effectively Connected Income — taxed at graduated rates (IRC §864)
- **Branch Profits Tax**: 30% on branch's dividend equivalent amount (IRC §884)
- **Treaty Benefits**: Limitation on Benefits clauses (LOB — IRC §7701(b))

## Transfer Pricing (IRC §482)
Arm's-length standard for related-party transactions
- **Methods**: CUP, Resale Price, Cost Plus, Profit Split, Transactional Net Margin (TNMM)
- **Documentation**: Penalty protection requires contemporaneous documentation (IRC §6662(e))
- **Advance Pricing Agreements (APA)**: Prospective resolution with IRS

## Foreign Information Reporting
- **Form 5471**: US owners of CFCs (by category — IRC §6038)
- **Form 8865**: Foreign partnership interests
- **Form 8938**: Specified foreign financial assets >$50K (FATCA — IRC §6038D)
- **FBAR (FinCEN 114)**: Foreign accounts >$10,000
- **Form 8833**: Treaty-based return positions
- **Penalties**: Up to $10K failure to file; willful FBAR violation — greater of $100K or 50% of account (31 U.S.C. §5321(a)(5))

## Tax Treaties
US has treaties with ~68 countries — key provisions:
- Reduced withholding rates
- Permanent establishment thresholds
- Exchange of information

## ContextCut Prompts
- "Compute GILTI inclusion for US shareholder with CFC net income of $[amount] and QBAI of $[amount]"
- "Determine FDII benefit for a US corporation with $[deduction eligible income] of foreign-derived income"
- "Is a US shareholder required to file Form 5471 for a foreign corporation with [ownership %, activities]?"
"""

files["cpa-corp-TRANSFER.md"] = """# Transfer Pricing (IRC §482)

## Arm's-Length Standard
IRC §482 authorizes IRS to allocate gross income, deductions, credits, or allowances among related entities to prevent tax evasion or clearly reflect income.

## Transfer Pricing Methods

### Traditional Transaction Methods
| Method | Description | Best For |
|--------|-------------|----------|
| CUP (Comparable Uncontrolled Price) | Price charged in comparable uncontrolled transaction (Treas. Reg. §1.482-3(b)) | Commodities, standardized products |
| Resale Price Method | Resale price minus appropriate gross profit margin (Treas. Reg. §1.482-3(c)) | Distributors |
| Cost Plus Method | Cost plus appropriate gross profit markup (Treas. Reg. §1.482-3(d)) | Manufacturers, contract service providers |

### Transactional Methods
| Method | Description | Best For |
|--------|-------------|----------|
| TNMM (Transactional Net Margin Method) | Net profit margin relative to appropriate base (Treas. Reg. §1.482-5) | Routine functions |
| Profit Split Method | Allocation based on relative contributions (Treas. Reg. §1.482-6) | Highly integrated operations, unique intangibles |

### Intangible Property (Treas. Reg. §1.482-4)
- **Category 1**: R&D cost sharing arrangements (CSA — Treas. Reg. §1.482-7)
- **Category 2**: Buy-in payment for pre-existing intangibles
- **Category 3**: Platform contribution transactions (PCT)

## Documentation Requirements (IRC §6662(e))

### Penalty Protection
Maintain contemporaneous documentation:
1. **Principal Documents**: Overview of business, controlled transactions, method selection, comparables, financial data
2. **Background Documents**: Contracts, financial statements, organizational charts, industry data
3. **Country-by-Country Report** (Base Erosion and Profit Shifting — BEPS Action 13): Required for parent entities with consolidated revenue ≥€750M (Treas. Reg. §1.6038-4)

### Master File and Local File (BEPS Action 13)
- **Master File**: Global business overview, supply chain, intangibles, financing (Form 5018)
- **Local File**: Detailed analysis of specific controlled transactions (Form 5017)

## Penalties
- **IRC §6662(e)**: 20% penalty on underpayment attributable to transfer pricing misstatement
- **IRC §6662(h)**: 40% "gross" misstatement (price ≥200% or ≤50% of arm's-length result)
- **Net Adjustment Threshold**: Transaction ≥$5M or net ≥$10M (for 20% penalty)

## Recent Developments
- *Amazon.com, Inc. v. Commissioner*, 148 T.C. No. 8 (2017) — cost-sharing buy-in
- *Coca-Cola Co. v. Commissioner*, 155 T.C. No. 10 (2020) — royalty rates for intangibles
- *3M Co. v. Commissioner*, 160 T.C. No. 3 (2023) — transfer pricing for foreign manufacturing

## ContextCut Prompts
- "Select the best transfer pricing method for a [function] between US parent and [country] subsidiary"
- "What contemporaneous documentation is needed to avoid IRC §6662(e) penalties for [company]'s related-party transactions?"
- "Analyze whether this intercompany royalty rate of [%] for [intangible] meets the arm's-length standard"
"""

# ═══════════════════════════════════════════════════════════════
# DOCTOR
# ═══════════════════════════════════════════════════════════════

files["doctor-CLINICAL.md"] = """# Clinical Documentation

## Documentation Principles
- **Timely**: Written at time of service or immediately after
- **Complete**: All relevant clinical data, findings, impressions, plans
- **Accurate**: Objective facts; avoid subjective language
- **Legible**: Electronic preferred; handwritten notes must be readable
- **SOAP Format**: Subjective, Objective, Assessment, Plan

## SOAP Note Structure
- **Subjective**: Patient's chief complaint, HPI, ROS, PMH, FH, SH
- **Objective**: Vital signs, physical exam findings, lab results, imaging
- **Assessment**: Differential diagnoses, clinical impressions, severity
- **Plan**: Diagnostic, therapeutic, patient education, follow-up

## Key Elements for Third-Party Payers
- Medical necessity clearly stated
- Appropriate ICD-10 codes linked to each diagnosis
- CPT codes for procedures with proper modifiers
- Time-based coding for E/M services (1995/1997 E/M Guidelines)
- Teaching physician documentation (Medicare Claims Processing Manual, Ch. 12, §100.1)

## Common Deficiencies
- Missing history of present illness (HPI) elements
- Incomplete review of systems (ROS)
- Lack of medical decision-making (MDM) complexity documentation
- Missing signature/dating of notes
- Use of unapproved abbreviations (Joint Commission "Do Not Use" list)

## ContextCut Prompts
- "Draft a SOAP note for a patient presenting with [symptoms] including [exam findings] and [labs]"
- "What ICD-10 codes correspond to this clinical presentation: [presentation]?"
- "Identify documentation gaps in this progress note: [note text]"
"""

files["doctor-REGULATORY.md"] = """# Healthcare Regulatory Compliance

## HIPAA Privacy Rule (45 CFR §160, §164)

### Protected Health Information (PHI)
Any individually identifiable health information held or transmitted by a covered entity or business associate.

### Permitted Uses and Disclosures
- **Treatment, Payment, Operations (TPO)** — 45 CFR §164.506
- **Required by Law** — 45 CFR §164.512(a)
- **Public Health Activities** — 45 CFR §164.512(b)
- **Law Enforcement** — 45 CFR §164.512(f)
- **Judicial Proceedings** — 45 CFR §164.512(e)

### Minimum Necessary Standard (45 CFR §164.502(b))
Must make reasonable efforts to limit PHI to minimum necessary to accomplish purpose.

### Notice of Privacy Practices (45 CFR §164.520)
Must provide notice describing uses/disclosures, individual rights, and covered entity's duties.

### Breach Notification (45 CFR §164.400-414)
- Risk assessment to determine probability of compromise
- Notification to individuals within 60 days
- Notification to HHS (500+ individuals — immediately; <500 — annual)
- Notification to media (if 500+ affected)

## Stark Law (42 U.S.C. §1395nn)
Physician self-referral prohibition — physician cannot refer Medicare patients to entity with which physician has financial relationship

### Exceptions
- In-office ancillary services
- Rental of office space/equipment (fair market value)
- Physician services personally performed by referring physician
- Group practice arrangements

### Penalties: False Claims Act liability, CMP ($15K-$100K per service), exclusion

## Anti-Kickback Statute (42 U.S.C. §1320a-7b(b))
Prohibits offering, paying, soliciting, or receiving remuneration for referrals

### Safe Harbors (42 CFR §1001.952)
- Investment interests (large publicly traded entities)
- Space and equipment rental (written agreement, FMV)
- Personal services (written, FMV, commercially reasonable)
- Managed care arrangements (risk-sharing)
- Electronic health records donations (interoperability requirements)

## CLIA (42 CFR §493)
Clinical Laboratory Improvement Amendments — certification required for lab testing

## ContextCut Prompts
- "Draft a HIPAA-compliant authorization form for disclosure of PHI for [purpose]"
- "Does this proposed arrangement [describe] violate the Stark Law, and which exception might apply?"
- "Create a HIPAA breach notification template for [scenario: lost laptop, hacked server, etc.]"
"""

files["doctor-BILLING.md"] = """# Medical Billing and Coding

## ICD-10-CM
International Classification of Diseases, 10th Revision, Clinical Modification
- **Format**: Letter + 2 digits + decimal + up to 4 alphanumeric characters (e.g., E11.649)
- **Exact Match**: Code to highest specificity
- **Laterality**: Right/left/bilateral when applicable
- **Combination Codes**: Single code for multiple conditions where available

## CPT Codes (Current Procedural Terminology)
Developed and maintained by AMA — 5-digit numeric codes

### E/M Coding (99202-99215)
Based on Medical Decision Making (MDM) or Time (2021/2023 revisions):
| Type | Level | MDM Level | Typical Time |
|------|-------|-----------|--------------|
| New Patient | 99202 | Straightforward | 15-29 min |
| New Patient | 99203 | Low | 30-44 min |
| New Patient | 99204 | Moderate | 45-59 min |
| New Patient | 99205 | High | 60-74 min |
| Established | 99212 | Straightforward | 10-19 min |
| Established | 99213 | Low | 20-29 min |
| Established | 99214 | Moderate | 30-39 min |
| Established | 99215 | High | 40-54 min |

### Modifiers
- **-25**: Significant, separately identifiable E/M service on same day as procedure
- **-59**: Distinct procedural service
- **-76**: Repeat procedure by same physician
- **-RT/-LT**: Right/left side
- **-GA**: Waiver of liability statement issued

## CMS (Medicare/Medicaid)

### Medicare Parts
- **Part A**: Hospital insurance (inpatient, skilled nursing, hospice)
- **Part B**: Medical insurance (outpatient, physician services, DME)
- **Part C**: Medicare Advantage (private plans)
- **Part D**: Prescription drug coverage

### Medicare Reimbursement
- **Fee Schedule**: Medicare Physician Fee Schedule (MPFS)
- **MACRA**: Merit-based Incentive Payment System (MIPS) — quality, cost, improvement activities, promoting interoperability
- **Advanced APMs**: Alternative Payment Models — qualify for 5% incentive

## Common Denial Reasons
- Medical necessity not established
- Incorrect patient identifier
- Timely filing limit exceeded
- Duplicate claim
- Non-covered service
- Bundled services (NCCI edits)

## ContextCut Prompts
- "Select the appropriate E/M code for a [new/established] patient visit with [MDM level or time] and [problem description]"
- "What ICD-10 codes are required to support medical necessity for [procedure]?"
- "Draft a redetermination letter for a denied claim: [original claim, denial reason, supporting clinical documentation]"
"""

files["doctor-PATIENT.md"] = """# Patient Communication and Consent

## Informed Consent

### Elements of Informed Consent
1. **Diagnosis** — Nature of patient's condition
2. **Procedure** — Nature and purpose of proposed treatment
3. **Risks** — Material risks of proposed treatment
4. **Benefits** — Expected benefits
5. **Alternatives** — Reasonable alternatives (including no treatment)
6. **Questions** — Opportunity for patient to ask questions

### Standards
- **Reasonable Physician Standard**: What a reasonable physician would disclose (majority rule)
- **Reasonable Patient Standard**: What a reasonable patient would want to know (*Canterbury v. Spence*, 464 F.2d 772 (D.C. Cir. 1972))

### Special Consent Situations
- **Minors**: Parent/guardian consent required (emancipated minor exceptions)
- **Emergency**: Treatment without consent if immediate threat to life/health (implied consent)
- **Language Barriers**: Qualified medical interpreter required (Title VI of Civil Rights Act of 1964; 45 CFR §80.3)
- **Telemedicine**: Specific consent for remote services (varies by state)

## Advance Directives
- **Living Will**: End-of-life treatment preferences
- **Durable Power of Attorney for Health Care**: Agent appointed for medical decisions
- **Do Not Resuscitate (DNR)** : Orders in outpatient or hospital setting
- **POLST/MOLST**: Physician/Medical Orders for Life-Sustaining Treatment — actionable medical orders

## Patient Education Best Practices
- Use plain language (5th-6th grade reading level)
- Teach-back method ("Tell me in your own words...")
- Culturally competent materials
- Include visual aids where helpful
- Provide written instructions for medications and follow-up

## HIPAA Patient Rights
- Access to medical records (45 CFR §164.524)
- Amendment of records (45 CFR §164.526)
- Accounting of disclosures (45 CFR §164.528)
- Request restrictions (45 CFR §164.522)
- Confidential communications (45 CFR §164.522(b))

## ContextCut Prompts
- "Draft an informed consent form for [procedure] including all required elements under [state] law"
- "Explain [diagnosis] to a patient using plain language suitable for 6th-grade reading level"
- "Create a patient discharge summary and follow-up instructions for [condition]"
"""

files["doctor-RESEARCH.md"] = """# Clinical Research Methodology

## Study Types
| Type | Description | Evidence Level |
|------|-------------|----------------|
| Meta-Analysis | Statistical aggregation of multiple studies | I |
| Systematic Review | Comprehensive review of existing literature | I |
| Randomized Controlled Trial (RCT) | Random assignment to intervention/control | II |
| Cohort Study | Prospective observation of exposed vs. unexposed | III |
| Case-Control Study | Retrospective comparison with controls | IV |
| Cross-Sectional Study | Single point in time observation | V |
| Case Series | Descriptive report of cases | VI |
| Case Report | Single patient description | VII |

## Regulatory Framework

### IRB Approval (45 CFR §46 / 21 CFR §56)
- **Exempt**: Low risk, no identifiable data
- **Expedited**: Minimal risk, certain research categories
- **Full Board**: Greater than minimal risk
- **Continuing Review**: At least annually for expedited/full board

### Informed Consent for Research (21 CFR §50 / 45 CFR §46.116)
Required elements:
1. Statement that study involves research
2. Purpose, duration, procedures (experimental vs. standard)
3. Reasonably foreseeable risks
4. Reasonably expected benefits
5. Appropriate alternative treatments
6. Confidentiality protections
7. Compensation for injury (if more than minimal risk)
8. Contact information
9. Voluntary participation/withdrawal rights

### FDA Oversight
- **IND (Investigational New Drug)**: 21 CFR §312 — required for human drug trials
- **IDE (Investigational Device Exemption)**: 21 CFR §812 — required for device studies
- **Good Clinical Practice (GCP)** : International ethical and scientific quality standard (ICH E6)

## Data Management
- **HIPAA Authorization**: Separate from research consent (45 CFR §164.508)
- **De-identification**: Safe harbor (remove 18 identifiers — 45 CFR §164.514(b)) or expert determination
- **Limited Data Set**: Excludes direct identifiers (45 CFR §164.514(e))
- **Data Use Agreement**: Required for limited data set disclosure (45 CFR §164.514(e)(4))

## ClinicalTrials.gov Registration
- Required for certain clinical trials (FDA Amendments Act of 2007, 42 U.S.C. §282(j))
- Results submission within 12 months of completion

## ContextCut Prompts
- "Design an IRB application for a study on [topic] involving [population] with [procedures]"
- "Draft informed consent language for a [Phase I/II/III] clinical trial investigating [intervention]"
- "What HIPAA authorizations are needed for a study using existing medical records from [source]?"
"""

files["doctor-ETHICS.md"] = """# Medical Ethics

## Core Principles (Beauchamp & Childress)
1. **Autonomy**: Respect patient's right to make healthcare decisions
2. **Beneficence**: Act in patient's best interest
3. **Non-maleficence**: First, do no harm
4. **Justice**: Fair distribution of healthcare resources

## Informed Decision-Making
- Respect for autonomy requires meaningful informed consent
- Capacity assessment: ability to understand, appreciate, reason, communicate choice
- Surrogate decision-making: substituted judgment → best interest

## End-of-Life Ethics
- Withholding vs. withdrawing life-sustaining treatment (ethically equivalent)
- Physician-assisted death (legal in ~10 states + DC — specific statutory requirements)
- Palliative sedation (principle of double effect)
- Brain death determination (Uniform Determination of Death Act; standard neurological criteria)

## Professional Boundaries
- Sexual misconduct (absolute prohibition — AMA Code of Medical Ethics Opinion 9.1.1)
- Financial relationships with patients (avoid; protect against conflicts — Stark Law, AKS)
- Gifts from industry (PhRMA Code, Sunshine Act — 42 U.S.C. §1320a-7h)
- Social media boundaries (maintain professional separation; no patient identification)

## Ethical Dilemmas
- **Confidentiality vs. Duty to Protect**: *Tarasoff v. Regents of University of California*, 551 P.2d 334 (Cal. 1976) — duty to warn third parties
- **Futility**: Unilateral withholding of futile treatment (hospital ethics committee; state-specific standards)
- **Resource Allocation**: Pandemic triage protocols (crisis standards of care)
- **Religious Objections**: Conscientious refusal (emergency contraception, sterilization — state-specific protections)

## AMA Code of Medical Ethics
- **9.2.1**: Physicians should be aware of, and act consistently with, the principles of medical ethics
- **1.1.1**: Patient-physician relationship rooted in trust
- **10.1**: Reporting impaired or incompetent colleagues

## ContextCut Prompts
- "Analyze the ethical considerations in a case where [clinical scenario with ethical dilemma]"
- "What are the legal and ethical requirements for obtaining informed consent from a non-English-speaking patient?"
- "Draft an ethics consult note for a conflict between patient autonomy and medical futility: [scenario]"
"""

files["doctor-PRACTICE.md"] = """# Practice Management

## Practice Structures
- **Solo Practice**: Full autonomy; all overhead costs borne by physician
- **Group Practice**: Shared overhead, call coverage, economies of scale
- **Hospital-Employed**: Salary + benefits; less autonomy, no business risk
- **Concierge/DPC**: Direct retainer model; no insurance billing; limited panel
- **Accountable Care Organization (ACO)** : Value-based care; shared savings with Medicare

## Revenue Cycle Management
1. **Pre-Registration** — Insurance verification, authorization
2. **Check-In** — Demographics, copay collection, consent forms
3. **Charge Capture** — Encounter documentation, coding
4. **Claim Submission** — Electronic (EDI 837) or paper (CMS-1500)
5. **Payment Posting** — ERA (835) or manual posting
6. **Denial Management** — Appeals within timely filing (typically 90-180 days)
7. **Patient Collections** — Statements, payment plans, collections agency

## Coding Compliance
- **OIG Work Plan**: Annual audit focus areas
- **RAC Audits**: Recovery Audit Contractor reviews
- **ZPIC/UPIC Audits**: Unified Program Integrity Contractor reviews
- **Target Areas**: E/M level, prolonged services, telemedicine, incident-to billing
- **Compliance Toolkit**: Auditing, training, corrective action plan, hotline

## Quality Measures
| Program | Measures | Reporting Method |
|---------|----------|-----------------|
| MIPS | 6 quality measures (min) | Claims, registry, QCDR, EHR |
| MACRA | Composite score (0-100) | MIPS Value Pathways (MVPs) |
| NSQIP | Outcomes-based | Surgeon-reported |
| HEDIS | Health plan performance | NCQA |

## Operational Efficiency
- **Scheduling**: Open access, advanced access; minimize no-shows (reminders, overbooking)
- **Telemedicine**: Reimbursement parity (many states); technology requirements; licensure (interstate compacts — IMLC)
- **Staffing Ratios**: Physician:FTE support = 1:3-5 (varies by specialty)
- **Documentation Templates**: Structured data entry (SNOMED, ICD-10)

## ContextCut Prompts
- "Develop a revenue cycle assessment for a [specialty] practice with [patient volume, payer mix]"
- "Create an internal coding audit plan for E/M services focused on [specific risk area]"
- "Draft a telemedicine consent form and patient agreement compliant with [state] law"
"""

# ═══════════════════════════════════════════════════════════════
# ADDITIONAL PROFESSIONS
# ═══════════════════════════════════════════════════════════════

files["realtor-LISTING.md"] = """# Real Estate Listing Agreements

## Types of Listing Agreements
- **Exclusive Right to Sell**: Agent earns commission regardless of who procures buyer
- **Exclusive Agency**: Agent earns commission unless owner procures buyer
- **Open Listing**: Agent earns commission only if agent procures buyer

## Key Listing Agreement Terms
- **Listing Price**: Market analysis support; price adjustment schedule
- **Commission**: Percentage or flat fee; co-brokerage split
- **Term**: Typically 3-6 months; automatic termination vs. extension
- **MLS**: Mandatory or optional; MLS rules compliance
- **Marketing Plan**: Photography, virtual tour, open houses, online advertising
- **Home Warranty**: Seller-provided or optional
- **Broker Protection**: Commission protection after listing expires (safety period — typically 30-90 days)

## Seller Disclosures
- State-mandated disclosure requirements (varies)
- Material defects known to seller
- Lead-based paint (pre-1978 — federal law)
- Death/suicide stigma disclosures (state-specific)
- HOA/Condo documents
- Environmental hazards (radon, mold, asbestos, meth)

## MLS Rules Compliance
- Accurate listing data (NRDS ID required)
- Photo/listing content standards
- Coming Soon vs. Active status
- Showings instructions and contact info
- Commission field accuracy
- NAR Code of Ethics violation reporting

## ContextCut Prompts
- "Draft a comparative market analysis (CMA) for [property address] using comps: [comps]"
- "Create a marketing plan for a [property type] listed at $[price] in [neighborhood]"
- "What disclosures are required for the sale of a [property type] built in [year] in [state]?"
"""

files["realtor-CONTRACT.md"] = """# Real Estate Purchase Contracts

## Standard Contract Clauses
- Parties and Property Description
- Purchase Price and Earnest Money Deposit
- Financing Contingency (loan type, rate, points)
- Inspection Contingencies (general, pest, specialty)
- Appraisal Contingency
- Title and Survey
- Closing and Possession Dates
- Prorations (taxes, HOA, rents)
- Risk of Loss (before closing)
- Default and Remedies
- Dispute Resolution

## Common Addenda
- **Seller Financing Addendum**: Terms, interest rate, balloon payment
- **Short Sale Addendum**: Lender approval requirement
- **FHA/VA Addendum**: Specific loan program requirements
- **1031 Exchange Addendum**: Tax-deferred exchange cooperation
- **Buyer's Contingency Addendum**: Sale of buyer's current home
- **Lead-Based Paint Addendum**: Pre-1978 properties
- **Radon Addendum**: Testing and mitigation

## Earnest Money
- Typically 1-3% of purchase price
- Held in escrow (broker's trust account)
- Liquidated damages (typically purchase price if buyer defaults)
- Disputes: Mediation/arbitration or interpleader

## ContextCut Prompts
- "Review this real estate purchase contract and identify all deadlines and contingencies: [contract]"
- "Draft an addendum addressing [specific issue] for a [residential/commercial] purchase in [state]"
- "Calculate net proceeds for a seller with purchase price $[price], mortgage balance $[balance], commission [%], closing costs $[costs]"
"""

files["realtor-DISCLOSURE.md"] = """# Real Estate Disclosure Requirements

## Federal Disclosures
- **Lead-Based Paint**: Residential Lead-Based Paint Hazard Reduction Act (42 U.S.C. §4852d) — pre-1978; 10-day inspection period; EPA pamphlet
- **Property Report**: Interstate Land Sales Full Disclosure Act (15 U.S.C. §1701) — subdivision developers
- **Flood Zones**: National Flood Insurance Program — mandatory disclosure of flood zone status (Biggert-Waters Act)

## State-Specific Disclosures
- **Seller Property Disclosure Statement**: Varies by state; typically includes structural, mechanical, environmental, neighborhood factors
- **Material Facts**: Common law duty to disclose (*Johnson v. Davis*, 480 So. 2d 625 (Fla. 1985) — latent defects known to seller)
- **Stigmatized Properties**: Death, AIDS, haunted (*Stambovsky v. Ackley*, 572 N.Y.S.2d 672 (App. Div. 1991) — disclosure of psychological stigma)
- **Megan's Law**: Sex offender registry information (varying disclosure requirements by state)
- **Natural Hazards**: Earthquake fault zones, flood zones, fire hazard severity, seismic hazards (California — Natural Hazard Disclosure)

## Agency Disclosure
- **Dual Agency**: Where permitted — written consent required; limited confidentiality
- **Transaction Broker**: Limited agency (some states — facilitator role)
- **Designated Agency**: Different agents in same firm represent buyer and seller
- **No Agency**: Customer status — no fiduciary duties

## Fair Housing (Fair Housing Act, 42 U.S.C. §3601)
Protected classes: Race, color, national origin, religion, sex, familial status, disability
Steering, redlining, discriminatory advertising all prohibited

## ContextCut Prompts
- "List all state and federal disclosures required for a [property type] sale in [state]"
- "Draft a Seller Property Disclosure Statement for a [property type] built in [year]"
- "Does [fact about property] constitute a material fact requiring disclosure under [state] law?"
"""

files["advisor-INVESTMENT.md"] = """# Investment Advisory Framework

## SEC/RIA Regulation
- **Investment Advisers Act of 1940 (15 U.S.C. §80b)**: Registration requirement for advisers with AUM ≥$100M
- **State Registration**: ≤$100M AUM — generally state-registered (NASAA model rules)
- **Fiduciary Duty**: *SEC v. Capital Gains Research Bureau*, 375 U.S. 180 (1963) — affirmative duty of utmost good faith
- **Regulation Best Interest (Reg BI)** : 17 CFR §240.15l-1 — broker-dealer standard of care for retail customers (2019)

## Client Engagement Process
1. **Information Gathering** — Financial goals, risk tolerance, time horizon, tax situation
2. **Risk Assessment** — Standard deviation, beta, Sharpe ratio, maximum drawdown, VaR
3. **Asset Allocation** — Strategic vs. tactical; modern portfolio theory (Markowitz, 1952)
4. **Security Selection** — Individual securities vs. funds (ETFs, mutual funds)
5. **Implementation** — Account opening, funding, trade execution
6. **Monitoring and Rebalancing** — Periodic review; threshold-based rebalancing (±5% typically)

## Portfolio Management
- **Asset Classes**: Equities, fixed income, cash, alternatives (real estate, commodities, private equity, hedge funds)
- **Diversification**: Across asset classes, sectors, geographies, investment styles
- **Tax Management**: Tax-loss harvesting (not wash sale — IRC §1091), asset location, qualified dividends, municipal bonds
- **Factor Investing**: Size, value, momentum, quality, low volatility (Fama-French, 1993; Carhart, 1997)

## Compliance Requirements
- Form ADV Part 2A (Brochure) — annual delivery/avail ability
- Form ADV Part 3 (Relationship Summary — Form CRS)
- Privacy Policy (Regulation S-P — 17 CFR §248)
- Code of Ethics (access persons — personal trading)
- Custody Rule (surprise exams if adviser has custody)
- Books and Records Rule (17 CFR §275.204-2)

## ContextCut Prompts
- "Develop an investment policy statement (IPS) for a [age] year-old client with $[assets], goal [goal], risk tolerance [risk]"
- "Design a tax-efficient withdrawal strategy for a retired client with $[portfolio] in taxable, tax-deferred, and Roth accounts"
- "Analyze portfolio rebalancing needs: current allocation [stocks/bonds/cash] vs. target [target], consider transaction costs of [%]"
"""

files["advisor-ESTATE.md"] = """# Estate Planning Strategies

## Core Estate Planning Documents
- **Last Will and Testament**: Disposition of probate assets; executor appointment; guardianship for minors
- **Revocable Living Trust**: Avoid probate; privacy; incapacity planning
- **Durable Power of Attorney**: Financial management during incapacity
- **Healthcare Power of Attorney**: Medical decision-making
- **Living Will**: End-of-life care preferences
- **Beneficiary Designations**: Retirement accounts, life insurance, POD/TOD accounts

## Trust Types
| Trust Type | Funding | Tax Treatment | Purpose |
|------------|---------|---------------|---------|
| Revocable Living Trust | During lifetime | Grantor taxed (IRC §676) | Avoid probate, incapacity |
| Irrevocable Life Insurance Trust (ILIT) | Life insurance policy | Excluded from estate | Estate tax liquidity |
| Qualified Personal Residence Trust (QPRT) | Personal residence | Gift tax freeze | Transfer home at reduced gift value |
| Grantor Retained Annuity Trust (GRAT) | Income-producing assets | Annuity to grantor | Transfer appreciation tax-free |
| Spousal Lifetime Access Trust (SLAT) | Assets to trust for spouse | Gift tax use | Asset protection, estate freeze |
| Intentionally Defective Grantor Trust (IDGT) | Assets to trust | Grantor pays income tax | Freeze appreciation income-tax free |
| Charitable Remainder Trust (CRT) | Appreciated assets | Income stream + charitable deduction | Diversify without capital gains |
| Charitable Lead Trust (CLT) | Assets to charity first | Reduced estate/gift tax | Charitable goals with family benefit |

## Estate Tax Planning
- **Portability** (IRC §2010(c)): DSUE election on Form 706
- **Annual Exclusion Gifts** (IRC §2503(b)): $18K/donee (2024) — remove from estate
- **Medical/Educational Gifts** (IRC §2503(e)): Unlimited — must pay provider directly
- **529 Plans**: Superfund (5-year election — IRC §529(c)(2)(B))
- **Grantor Trusts**: Trust income taxed to grantor — trust assets grow free of income tax
- **Buy-Sell Agreements**: Cross-purchase vs. entity-purchase; funding with life insurance

## Business Succession
- **Family Limited Partnership (FLP)** : Valuation discounts (lack of marketability, minority interest)
- **ESOP**: Employee Stock Ownership Plan — tax-deferred sale for owner
- **GRAT/IDGT**: Transfer business appreciation
- **Installment Sale to IDGT**: Lock in valuation + installment note

## ContextCut Prompts
- "Design an estate plan for a married couple with $[net worth], including [specific assets like business, real estate, investments]"
- "Compare the benefits of a GRAT vs. SLAT for transferring $[amount] of [asset type] to the next generation"
- "Calculate estate tax liability using portability and bypass trust planning for a couple with $[total] (assume current exclusion)"
"""

files["advisor-RETIREMENT.md"] = """# Retirement Income Planning

## Retirement Income Sources
1. **Social Security** — Base income layer
2. **Pension/Annuities** — Guaranteed income
3. **Retirement Accounts** — 401(k), IRA, Roth
4. **Taxable Accounts** — Brokerage, savings
5. **Home Equity** — Reverse mortgage, downsizing

## Social Security Optimization
- **Full Retirement Age (FRA)** : 66-67 (depending on birth year)
- **Early Filing (age 62)**: Permanently reduced (~25-30%)
- **Delayed Filing Credits**: 8%/year between FRA and age 70
- **Spousal Benefits**: Up to 50% of worker's PIA
- **Survivor Benefits**: Up to 100% of deceased worker's benefit
- **File and Suspend / Restricted Application**: Limited by Bipartisan Budget Act of 2015

## Required Minimum Distributions (SECURE 2.0)
- **Starting Age**: 73 (born 1951-1959); 75 (born 1960+)
- **Uniform Lifetime Table**: IRS Publication 590-B
- **Penalty**: 25% of RMD shortfall (reduced to 10% if corrected timely — SECURE 2.0 §302)
- **Roth Accounts**: No RMDs for Roth IRAs; SECURE 2.0 eliminated Roth 401(k) RMDs

## Withdrawal Strategies
| Strategy | Description | Best For |
|----------|-------------|----------|
| Required Minimum | RMD only; use taxable for discretionary | Lower need, large taxable |
| Flooring | Guaranteed income + variable from portfolio | Risk-averse retirees |
| Total Return | Systematic withdrawals from balanced portfolio | Moderate risk tolerance |
| Bucket Strategy | Cash/bonds/equities buckets sequenced by spending timeline | Managing sequence risk |
| Guardrails | % withdrawal with ceiling/floor adjustments | Flexible spending capability |

## Sequence of Returns Risk
Greatest threat in first 5-10 years of retirement — mitigating strategies:
- Cash reserve/bond tent
- Dynamic spending rules (Guyton-Klinger decision rules)
- Partial annuitization
- Bond tent (increasing equity allocation before retirement, then declining)

## Medicare Planning
- **Initial Enrollment**: 3 months before/after 65th birthday
- **Part B Premium**: IRMAA surcharges for high-income beneficiaries (income from 2 years prior)
- **Medigap**: Guaranteed issue during 6-month open enrollment
- **Part D**: Drug coverage; donut hole coverage gap phased out by IRA 2022
- **Medicare Advantage**: Part C plans with network restrictions vs. Original Medicare + Medigap

## ContextCut Prompts
- "Create a retirement income plan for a [age] year old with $[portfolio] in [taxable/tax-deferred/Roth accounts], needing $[annual] income"
- "Optimize Social Security claiming strategy for a married couple aged [ages] with earnings histories of [amounts]"
- "Compare the tax efficiency of withdrawing from taxable vs. tax-deferred vs. Roth accounts for a retiree in the [bracket]% bracket"
"""

files["architect-CONTRACT.md"] = """# Architectural Design Agreements

## AIA Contract Families
- **B101**: Standard Form of Agreement Between Owner and Architect
- **B102**: Abbreviated Standard Form
- **B103**: For Large or Complex Projects
- **B104**: For Projects of Limited Scope
- **B105**: For Use on a Sustainable Project
- **B201**: Standard Form of Architect's Services — Design and Construction Contract Administration
- **B202**: Standard Form of Architect's Services — Program Management
- **B203**: Standard Form of Architect's Services — Site Evaluation
- **B204**: Standard Form of Architect's Services — LEED Certification
- **B205**: Standard Form of Architect's Services — Historic Preservation

## Key Contract Provisions

### Scope of Services
- **Basic Services**: Schematic design, design development, construction documents, bidding/negotiation, construction administration
- **Additional Services**: Programming, environmental studies, existing conditions surveys, renderings, cost estimating, LEED/sustainability, commissioning, post-occupancy evaluation
- **Change Orders**: Written authorization required before additional work

### Compensation Methods
- **Percentage of Construction Cost**: Typically 6-15% (varies by project type and complexity)
- **Fixed Fee/Stipulated Sum**: Fixed price for defined scope
- **Hourly/Multiple of Direct Personnel Expense**: Time + expenses + multiplier
- **Hourly with Guaranteed Maximum**: Time billed up to cap

### Risk Allocation
- **Standard of Care**: AIA B101 §2.2 — professional skill and care ordinarily exercised by architects in same locale
- **Limitation of Liability**: AIA B101 §8.1.3 — typically limited to $50K or architect's fee, whichever is greater
- **Indemnification**: Mutual — each party indemnifies for their own negligence
- **Waiver of Consequential Damages**: AIA B101 §8.1.2 — mutual waiver

## ContextCut Prompts
- "Draft an owner-architect agreement (AIA B101) for a [project type] with a budget of $[amount] and schedule of [timeline]"
- "Review this design services agreement and identify risk allocation concerns: [contract excerpts]"
- "What additional services should be included for a [project type] with [specific requirements]?"
"""

files["architect-REGULATORY.md"] = """# Building Codes and Zoning

## International Codes (I-Codes)
Developed by International Code Council (ICC):
- **IBC**: International Building Code — structural, fire, means of egress
- **IRC**: International Residential Code — one- and two-family dwellings
- **IFC**: International Fire Code
- **IEBC**: International Existing Building Code
- **IMC**: International Mechanical Code
- **IPC**: International Plumbing Code
- **IECC**: International Energy Conservation Code
- **IgCC**: International Green Construction Code

## Key IBC Requirements
- **Chapter 3**: Occupancy Classification and Use
- **Chapter 5**: General Building Heights and Areas (allowable area increases)
- **Chapter 6**: Types of Construction (Type I-V — fire resistance ratings)
- **Chapter 7**: Fire and Smoke Protection Features
- **Chapter 9**: Fire Protection Systems (sprinklers, alarms, standpipes)
- **Chapter 10**: Means of Egress (occupant load, exit capacity, travel distance)
- **Chapter 11**: Accessibility (ADAAG / ICC A117.1)
- **Chapter 12**: Interior Environment (daylight, ventilation, sound transmission)
- **Chapter 13**: Energy Efficiency (references IECC)
- **Chapter 14**: Exterior Walls
- **Chapter 15**: Roof Assemblies and Rooftop Structures
- **Chapter 16**: Structural Design (loads — dead, live, snow, wind, seismic)

## Zoning Compliance
- **Use Groups**: Permitted, conditional, accessory, prohibited
- **Dimensional Standards**: Lot coverage, FAR (Floor Area Ratio), setbacks, height limits
- **Parking**: Minimum/maximum; bicycle, EV, loading
- **Landscaping**: Buffer yards, tree preservation, permeable surfaces
- **Signage**: Area, height, illumination, digital restrictions (interim *Reed v. Town of Gilbert*, 576 U.S. 155 (2015))
- **Variance Procedure**: Area vs. use; practical difficulty/undue hardship
- **Special Use Permit**: Public hearing process; conditions of approval

## Accessibility (ADA / FHA)
- **ADA Standards**: 2010 Standards for Accessible Design (28 CFR §35, 36 CFR §1191)
- **Fair Housing Act**: Design and construction requirements for multi-family (7+ units after March 1991)
- **UFAS**: Uniform Federal Accessibility Standards (federally funded projects)
- **ICC A117.1**: Accessible and Usable Buildings and Facilities (adopted by most states)

## Energy Codes
- **IECC 2021/2024**: Insulation, fenestration, air leakage, lighting, HVAC
- **ASHRAE 90.1**: Commercial buildings (alternative compliance path)
- **Title 24**: California's unique energy code (CALGreen)
- **Net-Zero Provisions**: Increasing adoption in state and local codes

## ContextCut Prompts
- "Determine the IBC occupancy classification and construction type for a [building description]"
- "Check zoning compliance for a [proposed use] on a lot zoned [zone] with dimensions [lot size]: [specific requirements]"
- "What accessibility requirements apply to a [building type] under the 2010 ADA Standards and 2021 IBC?"
"""

files["tech-PRIVACY.md"] = """# Data Privacy and Protection

## Major Privacy Frameworks

### GDPR (Regulation (EU) 2016/679)
- **Territorial Scope**: Article 3 — EU establishment, targeting EU residents, monitoring behavior
- **Lawful Basis**: Article 6 — consent, contract, legal obligation, vital interest, public task, legitimate interest
- **Data Subject Rights**: Articles 15-22 — access, rectification, erasure, restriction, portability, objection
- **Breach Notification**: Articles 33-34 — 72 hours to supervisory authority
- **DPO**: Article 37 — required for public bodies, large-scale monitoring, special categories
- **Fines**: Article 83 — greater of €20M or 4% of worldwide annual revenue
- *Case C-311/18 Data Protection Commissioner v. Facebook Ireland (Schrems II)* — SCCs adequacy

### CCPA / CPRA (Cal. Civ. Code §1798.100)
- **Applicability**: For-profit; gross revenue >$25M; 50K+ consumers; 50%+ revenue from selling PI
- **Consumer Rights**: Know, delete, opt-out, non-discrimination, correct (CPRA), limit sensitive data (CPRA)
- **Private Right of Action**: Only for data breaches (Cal. Civ. Code §1798.150)
- **CPRA Amendments**: Effective Jan 1, 2023 — new category of sensitive PI; broader opt-out rights

### US State Laws
- **VCDPA** (Virginia): Effective Jan 1, 2023
- **ColoPA** (Colorado): Effective July 1, 2023
- **CTDPA** (Connecticut): Effective July 1, 2023
- **UCPA** (Utah): Effective Dec 31, 2023
- **TIPA** (Texas): Effective July 1, 2024
- **OCPA** (Oregon): Effective July 1, 2024
- **MCDPA** (Montana): Effective Oct 1, 2024
- **FDBR** (Florida): Effective July 1, 2024 (digital bill of rights)

### HIPAA (45 CFR §160, §164)
Covered entities + business associates: PHI protection, breach notification, patient rights

## Privacy Program Implementation
1. **Data Inventory** — What data is collected, stored, processed, shared
2. **Risk Assessment** — DPIA (GDPR Article 35), PIAs
3. **Privacy Notice** — Clear, concise, transparent
4. **Consent Management** — Granular, withdrawable, auditable
5. **Vendor Management** — DPA (Data Processing Agreements), TIA (Transfer Impact Assessments)
6. **Incident Response** — Detection, containment, investigation, notification
7. **Training** — Annual employee privacy training

## ContextCut Prompts
- "Draft a GDPR-compliant privacy notice for a [company type] that collects [data types] from [users]"
- "Is a Data Processing Agreement (DPA) required with [vendor] who processes [data] for [purpose]? What clauses are mandatory?"
- "Create a data breach response checklist under GDPR and CCPA for a [scenario: ransomware, lost laptop, insider threat]"
"""

files["tech-CONTRACT.md"] = """# Software Licensing and SaaS Agreements

## License Types
| License | Ownership | Usage Rights | Examples |
|---------|-----------|--------------|----------|
| Perpetual | Customer owns copy | Indefinite use | Microsoft Office (pre-365) |
| Subscription | Vendor retains | Time-limited | SaaS, cloud services |
| Concurrent/ Floating | Vendor retains | Simultaneous user cap | Enterprise software |
| Site/Enterprise | Vendor retains | Unlimited users at location | Corporate agreements |
| Per-User/ Named | Vendor retains | Specific named users | CRM, ERP systems |
| Community/ Educational | Publisher | Free/ discounted use | Non-profit, academic |

## Key SaaS Agreement Provisions

### Service Level Agreement (SLA)
- Uptime guarantee (typically 99.5-99.99%)
- Calculation methodology (monthly, annual)
- Service credits (typically 5-25% of monthly fees)
- Exclusions (maintenance, force majeure, ISP issues)

### Data Ownership and Portability
- Customer data = customer property
- Right to extract data upon termination (reasonable format)
- Deletion obligation upon termination (with legal hold exception)
- Data Processing Agreement (DPA) for GDPR compliance

### Security
- SOC 2 Type II (or Type I)
- ISO 27001 certification
- Encryption (at rest: AES-256; in transit: TLS 1.2+)
- Incident response commitment
- Breach notification timeline

### Pricing
- Per-seat, consumption-based, flat fee
- Price protection (typically 1-3 years)
- Overages (pricing, thresholds)
- True-up / true-down rights

### Limitation of Liability
- Mutual exclusion of consequential damages
- Cap on direct damages (typically 3-12 months' fees)
- Exclusions from cap (IP indemnity, confidentiality breach, death/injury)

## Open Source Licensing
- **Permissive**: MIT, Apache 2.0, BSD — minimal restrictions
- **Weak Copyleft**: LGPL, MPL, Eclipse — link without copyleft trigger
- **Strong Copyleft**: GPL, AGPL — derivative works must be same license
- **AGPL**: Network use = distribution (trigger for SaaS)

## ContextCut Prompts
- "Draft a SaaS agreement for a [software type] with expected [users], [data types], and [pricing model]"
- "Review this SLA for appropriate uptime commitments and service credit structure: [SLA text]"
- "Can we use this [open source library] under [license] in our proprietary SaaS product? [usage description]"
"""

files["consultant-ENGAGEMENT.md"] = """# Consulting Engagement Letters

## Essential Engagement Letter Terms
1. **Parties** — Full legal names and addresses
2. **Scope of Services** — Specific deliverables, activities, exclusions
3. **Timeline** — Start/end dates, milestones, deliverable schedule
4. **Fees and Expenses** — Rate structure, invoicing, payment terms
5. **Termination** — For cause, for convenience, notice periods
6. **Confidentiality** — NDA obligations; exclusions
7. **IP Ownership** — Deliverable ownership; pre-existing IP license
8. **Independent Contractor** — No employment relationship
9. **Limitation of Liability** — Cap on damages; exclusions
10. **Dispute Resolution** — Mediation/arbitration; governing law

## Fee Structures
| Structure | Description | Best For |
|-----------|-------------|----------|
| Hourly/ Daily | Time × rate | Variable scope, advisory |
| Fixed Fee | Stipulated sum for defined scope | Well-defined deliverables |
| Retainer | Pre-paid block of time/month | Ongoing advisory |
| Value-Based | Fee tied to measurable outcomes | Strategic projects |
| Contingency | Fee based on results | Turnaround, fundraising |
| Success Fee | Bonus on achieving milestones | Growth-stage engagements |
| Gain-Sharing | % of cost savings | Operational improvement |

## Statement of Work (SOW) Structure
- **Objectives**: Clear, measurable goals
- **Approach/Methodology**: How work will be performed
- **Deliverables**: Specific outputs with acceptance criteria
- **Timeline**: Milestone dates, interim and final deliverables
- **Assumptions**: Conditions that scope depends on
- **Exclusions**: Explicitly what is NOT included
- **Client Responsibilities**: Data access, personnel availability, approvals
- **Success Criteria**: How completion/efficacy is measured

## ContextCut Prompts
- "Draft an engagement letter for a [type] consulting project with scope [description], timeline [duration], and fee [structure]"
- "Create a SOW for a [consulting service type] engagement including milestones, deliverables, and acceptance criteria"
- "Review this consulting agreement for independent contractor classification risk: [agreement text]"
"""

files["consultant-DELIVERABLE.md"] = """# Consulting Deliverable Frameworks

## Deliverable Types

### Diagnostic/Assessment
- **Current State Assessment**: As-is analysis, gap identification
- **Maturity Model**: Framework-based capability assessment (e.g., CMMI)
- **Benchmarking**: Comparative analysis against peers/industry
- **SWOT/TOWS Analysis**: Strengths, Weaknesses, Opportunities, Threats

### Strategy
- **Strategic Plan**: Vision, mission, goals, initiatives, KPIs
- **Business Case**: Problem/opportunity, options analysis, recommendation, financials
- **Go-to-Market Plan**: Customer segments, value proposition, channels, pricing
- **Roadmap**: Phased implementation timeline with dependencies

### Operational
- **Process Documentation**: Process maps (SIPOC, flowcharts, swimlanes)
- **Standard Operating Procedures (SOPs)** : Step-by-step operational instructions
- **Playbook**: Reusable methodology/template for common scenarios
- **Implementation Plan**: Tasks, owners, timelines, resources, risks

### Technology
- **Requirements Document**: Functional and non-functional requirements
- **Architecture Design**: System architecture, data flow, integrations
- **Vendor Evaluation**: RFP, scoring matrix, recommendation
- **Test Plan**: Test scenarios, cases, success criteria

## Deliverable Quality Standards
- **Clear Purpose**: Executive summary sets context
- **Structured**: Consistent headings, table of contents, appendices
- **Actionable**: Specific recommendations with implementation steps
- **Supported**: Data-driven analysis; assumptions stated
- **Professional**: Formatting, branding, error-free

## Common Frameworks
| Framework | Application | Origin |
|-----------|-------------|--------|
| MECE | Issue structuring | McKinsey |
| Pyramid Principle | Communication | Barbara Minto |
| 80/20 (Pareto) | Prioritization | Vilfredo Pareto |
| PDCA (Plan-Do-Check-Act) | Continuous improvement | Deming / TQM |
| Kotter 8-Step | Change management | John Kotter |
| ADKAR | Change management | Prosci |
| Balanced Scorecard | Strategy execution | Kaplan & Norton |
| Three Horizons | Innovation strategy | McKinsey / Baghai |

## ContextCut Prompts
- "Structure a consulting deliverable for a [project type] using the Pyramid Principle, starting with the key recommendation: [recommendation]"
- "Create an executive summary template for a [assessment/strategy/implementation] engagement"
- "Draft a client-ready slide deck outline for presenting [topic] using the Minto Pyramid Principle"
"""

files["consultant-METHODOLOGY.md"] = """# Consulting Methodologies

## Structured Problem Solving

### McKinsey/BCG/Bain Approach
1. **Define the Problem** — MECE issue breakdown
2. **Structure** — Issue tree / hypothesis tree
3. **Prioritize** — 80/20 on highest-impact issues
4. **Analyze** — Data collection, fact-based analysis
5. **Synthesize** — Findings → insights → recommendations
6. **Present** — Pyramid Principle structure; storyline

### Hypothesis-Driven Consulting
- State the hypothesis before collecting data
- Design analysis to prove or disprove
- Iterate: Refine hypothesis → additional analysis → revised conclusion
- *The McKinsey Way* (Rasiel): "Fact-based, hypothesis-driven"

## Analysis Tools

### Financial Analysis
- **DCF**: Discounted Cash Flow valuation
- **NPV/IRR**: Net Present Value / Internal Rate of Return
- **Break-Even Analysis**: Fixed vs. variable costs; contribution margin
- **Scenario Analysis**: Base, upside, downside cases
- **Sensitivity Analysis**: Key value drivers (what if?)

### Strategic Analysis
- **Porter's Five Forces**: Industry rivalry, new entrants, substitutes, supplier power, buyer power (Porter, 1979)
- **PESTLE**: Political, Economic, Social, Technological, Legal, Environmental
- **SWOT/TOWS**: Internal (Strengths, Weaknesses) × External (Opportunities, Threats)
- **Ansoff Matrix**: Market penetration, development, product development, diversification
- **BCG Matrix**: Stars, Cash Cows, Question Marks, Dogs
- **GE-McKinsey Matrix**: Industry attractiveness × business unit strength
- **VRIO Framework**: Value, Rarity, Imitability, Organization (Barney, 1991)

### Operational Analysis
- **Value Stream Mapping**: End-to-end process flow; cycle time; value-added ratio
- **Lean / Six Sigma**: DMAIC (Define, Measure, Analyze, Improve, Control)
- **Theory of Constraints**: Identify bottleneck → exploit → subordinate → elevate (Goldratt, 1984)
- **Kaizen**: Continuous incremental improvement

## Engagement Lifecycle
1. **Sell** — Proposal, chemistry meetings, references
2. **Launch** — Kickoff, data request, team setup
3. **Discover** — Interviews, research, data collection
4. **Analyze** — Modeling, hypothesis testing
5. **Develop** — Recommendations, implementation plan
6. **Present** — Final deliverable, board presentation
7. **Close** — Knowledge transfer, lessons learned

## Communication Frameworks
- **Pyramid Principle** (Barbara Minto): Top-level answer first → supporting arguments → data
- **Situation-Complication-Resolution**: Classic executive narrative
- **Storyboarding**: Visual outline of key messages per slide/chapter
- **Answer-First**: Never bury the conclusion

## Client Management
- **Day 1**: Align on expectations, success criteria, communication cadence
- **Weekly Check-in**: Progress, issues, decisions needed, next steps
- **Steering Committee**: Monthly executive-level review
- **Change Management**: Stakeholder buy-in, communication plan, training
- **Closeout**: Lessons learned, knowledge transfer, follow-up plan

## ContextCut Prompts
- "Structure a problem-solving approach for a client facing [issue] in [industry] using the MECE hypothesis tree"
- "Apply Porter's Five Forces to [industry] and identify strategic implications for a [company type]"
- "Design a 12-week consulting engagement for [project type] with key milestones and deliverables"
"""


# ═══════════════════════════════════════════════════════════════
# WRITE ALL FILES
# ═══════════════════════════════════════════════════════════════

for name, content in files.items():
    path = BASE / name
    path.write_text(content.strip())
    print(f"  Created: {name} ({len(content)} bytes)")

print(f"\nDone. {len(files)} files created in {BASE}")
