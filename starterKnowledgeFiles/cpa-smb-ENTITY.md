# Business Entity Taxation

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