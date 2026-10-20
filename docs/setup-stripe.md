# Stripe setup

Visitors can support the forecast monthly or once. Each option is a Stripe Payment Link, so there is no checkout code and no webhook on our side. The page shows the support section only when every link in `site.support` in `config/pegel.json` is set. All of this is done once in the Stripe dashboard.

1. **Product.** Name it "Unterstützung", not "Spende": Energiekonzepte Ruhr is a business and can't issue donation receipts.
2. **Payment methods.** Under Settings → Payment methods, turn on cards, Apple Pay, Google Pay and PayPal.
3. **Payment Links.** Create seven, all in EUR:
   - recurring, monthly: 2 €, 5 €, 10 € (tiers `zentimeter`, `dezimeter`, `meter`)
   - one-off: 5 €, 10 €, 20 €
   - one-off, "Customers choose what to pay", with a minimum (e.g. 3 €)
4. **Redirect after payment.** In each link, under "After payment", choose "Don't show confirmation page" and redirect to:
   - monthly links: `https://deilbach-pegel.energiekonzepte-ruhr.de/?danke=<tier id>`, e.g. `?danke=dezimeter`
   - one-off and free amount: `https://deilbach-pegel.energiekonzepte-ruhr.de/?danke=einmalig`
5. **Customer portal.** Under Settings → Billing → Customer portal, turn it on and allow cancelling and changing the plan. Then the receipt email carries a link to manage the subscription; the page promises "monatlich jederzeit kündbar".
6. **Config.** Paste the seven URLs into `site.support` in `config/pegel.json`: each tier's `url`, each `one_off` amount's `url`, and the free amount as `custom_url`. Merge; the section and the footer link appear with the next deploy. If a link is missing, the page shows none of it.
7. Pay one small amount yourself with each kind of link and check the redirect and the receipt email. Refund it in the dashboard.
