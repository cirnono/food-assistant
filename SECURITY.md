# Security Policy

## Reporting a vulnerability

Report vulnerabilities privately through the repository's GitHub private
security advisory feature. If that feature is unavailable, contact the
maintainer through a private channel listed on their GitHub profile. Do not put
tokens, request headers, private URLs, recipe data, or exploit details in a
public issue.

Include affected versions, impact, reproduction steps using placeholders, and
a proposed mitigation when possible. Maintainers will acknowledge a report and
coordinate disclosure after a fix is available.

## If a secret is exposed

1. Revoke or rotate the Food Assistant, Mealie, and LLM credentials at their
   respective services immediately.
2. Replace the server-side environment variable or secret file.
3. Recreate the application container.
4. Review proxy, provider, and application logs for unauthorized use.
5. Remove the value from Git history before publishing, but do not treat history
   rewriting as a substitute for rotation.

Docker Secrets and `*_FILE` variables are recommended. AI API keys must stay on
the server and must never be placed in browser HTML, JavaScript, localStorage,
URLs, screenshots, or issue reports.

Before public exposure, configure strong API authentication and HTTPS. The
`/review` document itself is public by default even though its API calls require
authentication; protect it with reverse-proxy access control. When using
Cloudflare Tunnel or another proxy, restrict origin access, validate forwarded
headers, enable TLS to the appropriate boundary, and avoid logging authorization
headers or query strings containing credentials.
