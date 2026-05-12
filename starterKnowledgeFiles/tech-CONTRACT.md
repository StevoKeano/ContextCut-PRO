# Software Licensing and SaaS Agreements

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