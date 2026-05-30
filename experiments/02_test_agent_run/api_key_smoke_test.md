# API Key Smoke Test

Create a small, auditable smoke test of the API credentials available inside the
agent runtime.

Plan this as a single short execution phase. The first worker phase should
enumerate credentials, run the minimal provider probes, audit for leaked secret
values, and write the final report artifacts. Do not spend a whole phase only
building scaffolding.

Do not print, copy, or save raw secret values. Redact all credentials in logs and
reports. It is acceptable to print environment variable names and whether a value
is present.

## Objective

Determine which API credentials the agent can see, and whether recognized
provider keys work for minimal authenticated requests.

## Required Work

1. Enumerate environment variables that look like credentials, including names
   matching `*_API_KEY`, `*_TOKEN`, `*_ACCESS_TOKEN`, `*_SECRET`, and common
   provider variables such as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `OPENROUTER_API_KEY`, `TOGETHER_API_KEY`, `GEMINI_API_KEY`,
   `GOOGLE_API_KEY`, and `FIREWORKS_API_KEY`.
2. Record only the variable name, whether it is present, and a safe redacted
   shape such as prefix length, suffix length, and total length. Do not reveal
   the actual prefix or suffix.
3. For recognized providers with present keys, run the cheapest safe
   authentication check you can:
   - Prefer list-models or account metadata endpoints when available.
   - If a provider requires a model call, use a tiny request with `max_tokens`
     or equivalent set as low as practical.
   - Use short timeouts.
4. For unrecognized credentials, record them as "present but not tested" and
   explain why.
5. Write all outputs under `writeup/`:
   - `writeup/api_key_smoke_test.md`: human-readable summary table.
   - `writeup/api_key_smoke_test.json`: structured results.
   - `writeup/commands.md`: exact commands/scripts used, with no secrets.

## Acceptance Criteria

- The report clearly says which provider checks succeeded, failed, or were not
  attempted.
- No raw secret values appear in any file.
- Failures include concise error categories without leaking request headers.
- The final answer summarizes where the agent had credential access and whether
  the sandbox environment appears to have received the injected credentials
  (provided both as a `.env` file in the workspace and as environment variables).
