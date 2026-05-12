# International Tax

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