# Project maintenance

- Use Semantic Versioning for every user-requested application change without waiting for a reminder: patch for fixes, minor for backward-compatible features, major for breaking changes. Bump once per release, not per intermediate edit.
- Run `node scripts/version.mjs patch|minor|major` to synchronize frontend, backend, and Android versions. Run `node scripts/version.mjs --check` before publishing.
- Keep the version visible in the static footer on both login and application screens.
- Never commit passwords, signing secrets, API credentials, or private environment files. Password authentication belongs on the backend.
- Maintain the simple UI: required inputs and dropdowns; appearance and optional connection overrides in collapsed Settings.
- Verify API authentication, real conversion/download jobs, web build, and APK when relevant. Distinguish local verification from production verification.
- Free Render hosting has limited CPU/RAM, sleeps when idle, and has ephemeral storage. Do not promise universal downloads or unlimited processing; preserve private-network and authentication protections.
