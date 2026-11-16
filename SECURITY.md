# Security and deployment scope

KOL Desk is intended for one computer, bound to `127.0.0.1`. Default no-sign-in mode gives anyone using that local workspace the same editing and approval rights. Optional accounts do not isolate projects. Do not put this service on a public network without a separate deployment and security review.

Campaigns and provider evidence are stored in an unencrypted SQLite database. API keys entered in the UI live only in process memory. Environment-provided keys are the operator responsibility. Neither keys nor business databases belong in Git.

For a suspected vulnerability, avoid posting business information, API keys, provider responses, or database files in public issues. Use a minimal synthetic reproduction. Review reports before sharing them: business notes and creator information are intentionally preserved.

This project has not undergone a third-party security audit. Python and browser tests verify specific behaviors; they do not establish production hosting readiness.
