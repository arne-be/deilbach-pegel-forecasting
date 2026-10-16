# Domain setup

The website runs on `deilbach-pegel.energiekonzepte-ruhr.de`. The DNS stays at GoDaddy, where the main site (Lovable) keeps its own records. We only add two CNAMEs. CloudFront needs an ACM certificate from `us-east-1`, and ACM issues it only after it sees a validation record in DNS. So it takes one round trip, all of it once.

1. **Bootstrap.** The deploy role needs the ACM permissions in `infra/bootstrap/roles.tf`. Apply bootstrap by hand from the branch before merging (see [its README](../infra/bootstrap/README.md)).
2. **Merge.** The deploy requests the certificate. The `tofu apply` output `site_certificate_validation` holds the record, or read it later:
   ```
   cd infra/prod && tofu output site_certificate_validation
   ```
3. **Validation CNAME at GoDaddy.** In the DNS of `energiekonzepte-ruhr.de`, add a CNAME with `resource_record_name` without the trailing `.energiekonzepte-ruhr.de.` as name and `resource_record_value` as value. Keep it: ACM uses it for every automatic renewal.
4. **Wait** until the certificate shows "Issued" in the ACM console (region us-east-1), usually a few minutes. Or:
   ```
   aws acm list-certificates --region us-east-1 --query "CertificateSummaryList[].[DomainName,Status]"
   ```
5. **Switch it on.** Set `site_certificate_issued = true` in `infra/prod/website.tf` and merge. CloudFront now answers on the subdomain.
6. **Site CNAME at GoDaddy.** Name `deilbach-pegel`, value the CloudFront address from the output `site_url` without `https://` (`dxxxx.cloudfront.net`).
7. Link to `https://deilbach-pegel.energiekonzepte-ruhr.de` from the main site.
