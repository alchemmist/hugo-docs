# Native OpenID Connect (unreleased)

OIDC is opt-in. Existing installations without `WIKI_OIDC_ISSUER` retain their
current account authentication. When enabled, ordinary humans authenticate at the
identity provider, while an explicitly selected existing local administrator retains
an independent emergency password path. Public reading and MCP bearer credentials
are separate from browser login.

## Prerequisites and configuration

Back up the stopped runtime volume and account database before enabling federation.
Bootstrap a local emergency administrator first; obtain its exact account ID. Keep
its current password and a tested independent recovery path. Do not assume an old
initial-password file still contains a working password.

Provide these environment variables through an existing protected Kubernetes Secret
(or an equivalent secret store), never committed literal credentials:

- `WIKI_OIDC_ISSUER`: fixed HTTPS issuer, including its exact trailing-slash semantics.
- `WIKI_OIDC_CLIENT_ID`, `WIKI_OIDC_CLIENT_SECRET`: confidential code-flow client.
- `WIKI_OIDC_SESSION_SECRET`: persistent random state-cookie signing secret, >=32 characters.
- `WIKI_OIDC_LOCAL_OWNER_IDS`: JSON array of exact existing active administrator IDs.
- `WIKI_OIDC_GROUP_ROLES`: JSON object from admitted group names to reader/editor/admin.
- `WIKI_OIDC_LINKS`: optional JSON object from reviewed OIDC subjects to existing user IDs.
- `WIKI_OIDC_SUBJECT_ROLES`: optional explicit per-subject role mappings for reviewed
  pre-existing permissions; these override group-derived roles only for admitted users.

The chart's `oidcSecret` references that existing environment Secret. It never
creates client credentials or embeds their values in Helm configuration. Changing
the Secret requires a coordinated application restart; the chart does not read
secret contents to compute a checksum. Disable access logging of callback query
parameters, e.g. `UVICORN_ACCESS_LOG=false` with the standard Uvicorn entrypoint.

Configure a strict redirect URI `<public-origin><base-path>/api/auth/oidc/callback`.
The IdP must provide signed ID-token claims `iss`, `sub`, `preferred_username` and
an array-valued `groups` claim. Authlib handles authorization code, PKCE S256,
state, nonce, signing keys and token validation. Issuer is additionally pinned.

## Identity and authorization behavior

`/login` enters OIDC. `/login?local=1` displays the emergency local form, but the
backend permits password login only for the declared owner IDs, not every user
with an admin role. Ordinary pre-migration local sessions are rejected as well.
The fallback does not contact the identity provider.

No account is adopted by matching email or username. To preserve existing content,
preferences, API tokens and IDs, review the issuer/subject -> account-ID mapping
explicitly. An unlinked username collision is rejected. Disabled local accounts
remain blocked. New subjects receive new native accounts with no known local
password and cannot use local password login. No admitted group means no login.
Role changes invalidate existing sessions and API tokens for that account.

The application creates its normal secure, HttpOnly session cookie and retains
native CSRF/origin and role checks. Logout clears the Wiki session, not all IdP
sessions; a still-active IdP session can sign in again. IdP disablement is not
instant application-session revocation: coordinate session, API-key and account
revocation during offboarding. MCP still requires its scoped native bearer token;
an OIDC browser cookie is not an MCP credential.

## Acceptance and rollback

Verify owner OIDC, restricted roles, direct API write denial, ordinary local-login
and legacy-session denial, owner fallback without IdP access, logout, public reads
and existing MCP access. `runtime/tests/test_oidc.py` covers account-link and
fallback boundaries; provider-level browser acceptance is also necessary.

Preserve a protected full-volume backup, signing keys, client configuration and
current account passwords. This integration adds federation tables without deleting
existing hashes. Removing OIDC configuration re-enables former local authentication
semantics, so rollback is a security decision, not merely a Helm rollback. Do not
restore revoked credentials or overwrite accepted content blindly.
