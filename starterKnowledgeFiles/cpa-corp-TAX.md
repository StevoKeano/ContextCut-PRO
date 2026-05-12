# Corporate Taxation

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