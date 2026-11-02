# Review standard

Every PR is reviewed against this list. A change passes only when all five hold.

1. **Matches the spec and acceptance criteria.** Each criterion is met, and nothing was built that the spec did not ask for.
2. **Role checks are enforced server-side.** Hiding a button or link in a template is not a role check.
3. **No secrets.** No keys, passwords, or tokens in code, config, tests, or logs.
4. **Input is validated.** Anything from a user or an external system is validated before it is used.
5. **Readable for a Mendix developer.** Someone with limited Python experience can follow the change.
