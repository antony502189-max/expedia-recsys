# Security Policy

## Supported versions

Security fixes are applied to the current `main` branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, exposed credential, or sensitive dataset problem. Use GitHub's private security-advisory reporting for this repository when available; otherwise contact the repository owner privately through GitHub.

Please include a concise description, reproduction steps, affected paths or versions, and any suggested mitigation. Reports are acknowledged as soon as practical, and confirmed secrets are removed from the current branch immediately. Credential rotation remains the responsibility of the credential owner.

## Handling secrets and data

The repository must not contain raw competition data, generated data products, private keys, tokens, or `.env` files. Local data and delivery artifacts are excluded through `.gitignore`; configuration committed under `config/` must contain only non-sensitive contract data.
