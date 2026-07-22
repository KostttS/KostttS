# Technical Examples

Small, sanitized examples of patterns used in FlutterFlow and mobile-app projects.

These files demonstrate implementation approaches without exposing client data, API keys, private endpoints, or proprietary project code. Each example should be adapted to the database schema and naming conventions of a specific application.

## Included examples

- [Distance calculation and sorting](./distance_sorting.dart) — adds Haversine distance to JSON-like records and sorts service providers from nearest to farthest.
- [Payment return and status polling](./payment_return_and_polling.dart) — validates a deep-link return and polls a payment provider through an injected status request.
- [Supabase owner-based RLS](./supabase_owner_rls.sql) — public reading with authenticated owner-only insert and update; deletion remains disabled.
- [Firebase subscription expiry](./firebase_subscription_expiry.js) — scheduled Cloud Function v2 that marks expired subscriptions in batches.

## Typical FlutterFlow usage

These patterns can be connected to FlutterFlow as:

- Custom Actions or Custom Functions
- API Call wrappers
- Supabase SQL migrations
- Firebase Cloud Functions
- payment-result and deep-link flows

## Security

Production secrets belong in server-side environment configuration or a private secrets store. Never put service-role keys, payment secrets, or private API credentials in FlutterFlow client code or a public repository.
