# Configuration

Copy `.env.example` to `.env` for local development. Defaults are defined in
`packages/common/config.py`; processing jobs freeze nonsecret settings in the
database. Secrets never enter the frozen job configuration or generated artifacts.

Docker Compose explicitly supplies container addresses. Native scripts use the
published loopback addresses. Meta inference remains `fixture` until the owner
chooses the later live phase. No API key is needed to run offline checks.
