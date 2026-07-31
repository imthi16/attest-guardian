# Shared configuration

Reserved for typed environment contracts shared by more than one application.

**Nothing imports from here yet.** The API's settings live in `apps/api/app/config.py`, which is
the only consumer today; `docs/CONFIGURATION.md` is the reference for every variable.

Whatever lands here keeps the same rule: secrets remain process inputs and are never stored in a
generated artifact or a committed file.
