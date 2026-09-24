# MENTRA Integration Contract

Shared, versioned contracts for integrating the teacher workspace and classroom player into a SaaS host.

- Never use `*` as a `postMessage` target origin.
- The host and embedded application must validate both `event.origin` and the message envelope.
- Existing OpenMAIC routes remain available; this package is an additive integration seam.
