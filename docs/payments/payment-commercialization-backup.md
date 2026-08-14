# EnlyAI Payment Commercialization Backup

This module is a backup implementation for future commercialization. It is intentionally not linked from the current classroom, dashboard, or landing conversion flow.

## Payment research summary

Mainstream commercial sites usually split payment by market:

- China mainland: WeChat Pay and Alipay are table stakes. PC sites commonly use QR code payment, while WeChat in-app flows use JSAPI/OpenID. Alipay PC checkout redirects to the Alipay cashier, with Face-to-Face/QR as a desktop fallback.
- Global: Stripe Checkout is the common default for cards, Apple Pay, Google Pay, and localized payment methods. PayPal remains important for international users who prefer wallet payment.
- Architecture: sites keep a local order table as the source of product entitlement state, create a provider checkout session/order, redirect or show QR code, then rely on provider webhook/notify callbacks to mark the local order paid. Frontend polling is only a user-experience aid, not the source of truth.

## Implemented backup flow

- `app/payment-sandbox/page.tsx`: standalone payment sandbox page.
- `app/api/payments/catalog`: payment plans and methods.
- `app/api/payments/checkout`: creates a local payment order and provider checkout action.
- `app/api/payments/orders/[orderId]`: returns order status for polling.
- `app/api/payments/sandbox/complete`: local non-money payment completion for verification.
- `app/api/payments/webhooks/[provider]`: provider webhook entry point. Stripe signature verification, Alipay RSA2 notify verification, and WeChat Pay v3 signature/decryption hooks are included when the corresponding keys are configured.
- `lib/payments/*`: catalog, runtime config, order store, provider adapters, serialization, and checkout orchestration.
- `payment_orders` SQLite table: local payment order state machine.

## Supported providers

The code supports these provider paths:

- WeChat Pay: `wechat_native`, `wechat_jsapi`
- Alipay: `alipay_page`, `alipay_qr`
- Stripe: `stripe_checkout`
- PayPal: `paypal_checkout`
- Sandbox: `sandbox_checkout`

If live credentials are missing, checkout falls back to sandbox mode when `PAYMENT_SANDBOX_ENABLED` is not set to `false`. This lets staging/production deployments validate the flow without touching real funds.

## Environment variables

Common:

```bash
PAYMENT_PUBLIC_BASE_URL=https://www.enlyai.com
PAYMENT_SANDBOX_ENABLED=true
PAYMENT_ALLOW_EXTERNAL_RETURN_URLS=false
```

Stripe:

```bash
STRIPE_SECRET_KEY=sk_live_or_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

PayPal:

```bash
PAYPAL_ENV=sandbox # or live
PAYPAL_CLIENT_ID=xxx
PAYPAL_CLIENT_SECRET=xxx
```

Alipay:

```bash
ALIPAY_GATEWAY=https://openapi.alipay.com/gateway.do
ALIPAY_APP_ID=xxx
ALIPAY_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
ALIPAY_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
```

WeChat Pay:

```bash
WECHAT_PAY_MCH_ID=xxx
WECHAT_PAY_APP_ID=xxx
WECHAT_PAY_API_V3_KEY=xxx
WECHAT_PAY_SERIAL_NO=xxx
WECHAT_PAY_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
```

## Verification

Recommended local verification:

```bash
pnpm exec vitest run tests/payments/payment-catalog.test.ts tests/server/payment-route-contract.test.ts
pnpm exec tsc --noEmit --pretty false
pnpm build
```

Manual sandbox flow:

1. Open `/payment-sandbox`.
2. Select a CNY plan with WeChat/Alipay or a USD plan with Stripe/PayPal.
3. Create checkout.
4. Confirm the order enters `requires_action`.
5. Click `沙盒支付成功`.
6. Confirm the order enters `paid`.

## Future integration notes

When EnlyAI is ready to commercialize, connect the existing app flow to this module by:

1. Adding a pricing/checkout entry point.
2. Mapping paid orders to entitlement records or lesson credits.
3. Binding paid orders to entitlement records or lesson credits after finance rules are finalized.
4. Adding refund and subscription renewal flows.
5. Adding finance/admin views for reconciliation.
