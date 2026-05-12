# Medical Billing and Coding

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