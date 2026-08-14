# User Identity Verification & Registration Audit Design

## Background

Per China's Cybersecurity Law and Internet User Account Information Management Regulations,
online platforms must implement real-identity verification for users and retain registration
information long-term. This design adds phone number verification (SMS + number certification)
and comprehensive registration audit logging to EnlyAI.

## Scope

- **Method A (primary)**: SMS verification code via Alibaba Cloud SMS
- **Method B (enhanced)**: Alibaba Cloud Number Certification (one-tap login)
- **Audit logging**: Long-term retention of registration/login metadata per regulatory requirements

## Database Schema Changes

### users table — new columns

| Column | Type | Description |
|--------|------|-------------|
| phone | text, unique | Phone number (AES-256 encrypted at rest) |
| phoneVerified | integer (0\|1) | Whether phone is verified |
| phoneVerifiedAt | integer | Timestamp of phone verification |
| identityVerified | integer (0\|1) | Composite identity verification flag |

### New table: sms_verification_codes

Short-lived storage for SMS verification codes (auto-cleaned after expiry).

| Column | Type | Description |
|--------|------|-------------|
| id | text, pk | nanoid |
| phone | text, not null | Phone number |
| code | text, not null | 6-digit verification code |
| purpose | text, not null | 'register' \| 'login' \| 'bind_phone' \| 'reset_password' |
| expiresAt | integer | Expiry time (5 minutes) |
| usedAt | integer | When the code was used (null if unused) |
| createdAt | integer | Creation time |
| ipAddress | text | Request source IP |

### New table: user_registration_audit_logs

Long-term retention of registration/login events per regulatory requirements.

| Column | Type | Description |
|--------|------|-------------|
| id | text, pk | nanoid |
| userId | text, → users | Associated user |
| eventType | text, not null | 'register' \| 'login' \| 'phone_verify' \| 'identity_verify' |
| sourceIp | text | Source IP address |
| sourcePort | text | Source port |
| destIp | text | Destination IP (server) |
| destPort | text | Destination port |
| url | text | Request URL |
| method | text | HTTP method |
| userAgent | text | User-Agent header |
| verificationType | text | 'sms_code' \| 'number_cert' \| 'oauth' |
| verificationId | text | Linked verification record ID |
| phone | text | Phone number (encrypted) |
| accountId | text | User ID |
| nickname | text | Nickname at time of event |
| clientFingerprint | text | Browser hardware fingerprint hash |
| createdAt | integer | Record timestamp |

## SMS Verification Flow (Method A)

```
User enters phone → POST /api/sms/send-code
  ↓
Server generates 6-digit code → stores in sms_verification_codes → calls Alibaba Cloud SMS API
  ↓
User enters code → POST /api/sms/verify-code
  ↓
Code validated → marked as used → returns verification token (JWT, 10min TTL)
  ↓
Register/login with verification token → identity verified
```

### Rate limiting

- Same phone: 1 request per 60 seconds
- Same IP: 10 requests per hour
- Code expires in 5 minutes
- Same phone: max 5 codes per day

## Number Certification Flow (Method B)

```
Frontend calls Alibaba Cloud Number Cert SDK → obtains token
  ↓
POST /api/auth/number-cert-verify { token }
  ↓
Server calls Alibaba Cloud Number Cert API → retrieves phone number
  ↓
Auto-verified, no code input needed
```

## Registration Flow Redesign

Current: `email + password + nickname → register`

New (two-step):

1. **Step 1**: Enter phone → send code → verify → receive verification token
2. **Step 2**: Enter email + password + nickname + verification token → register
3. **After registration**: Write audit log with all required fields

Alternative (one-tap via Method B): Skip step 1 entirely.

## Client Fingerprint

Collect browser fingerprint (Canvas, WebGL, AudioContext) using a lightweight implementation.
Generate SHA-256 hash, submit with register/login requests.

## API Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/api/sms/send-code` | POST | Send SMS verification code |
| `/api/sms/verify-code` | POST | Verify SMS code, return verification token |
| `/api/auth/number-cert-verify` | POST | Alibaba Cloud number certification |
| `/api/auth/register` | POST | Modified: requires phone + verification token |
| `/api/auth/login` | POST | Modified: writes audit log |
| `/api/auth/bind-phone` | POST | Bind phone to existing account |

## Environment Variables

```
# Alibaba Cloud SMS
ALIYUN_SMS_ACCESS_KEY_ID=
ALIYUN_SMS_ACCESS_KEY_SECRET=
ALIYUN_SMS_SIGN_NAME=
ALIYUN_SMS_TEMPLATE_CODE=

# Alibaba Cloud Number Certification
ALIYUN_NUMBER_CERT_ACCESS_KEY_ID=
ALIYUN_NUMBER_CERT_ACCESS_KEY_SECRET=

# Phone encryption key (AES-256)
PHONE_ENCRYPTION_KEY=
```

## Security Considerations

- Phone numbers encrypted at rest with AES-256-GCM
- Verification tokens are short-lived JWTs (10 minutes)
- SMS codes are one-time use, marked as used after verification
- Audit logs are append-only, never deleted
- Rate limiting on all verification endpoints
- Client fingerprint is a hash, no raw device data stored

## Implementation Order

1. Database schema changes (users columns + new tables)
2. SMS verification service (Alibaba Cloud SMS integration)
3. Registration audit logging
4. Register/login API modifications
5. Frontend: phone verification step in registration
6. Client fingerprint collection
7. Number certification (Method B)
8. Environment variables + .env.example
9. i18n translations
10. Tests
