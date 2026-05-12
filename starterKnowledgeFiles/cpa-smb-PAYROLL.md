# Payroll Tax Compliance

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