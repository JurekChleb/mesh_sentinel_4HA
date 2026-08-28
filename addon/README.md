# Mesh Sentinel app

Build context for the Home Assistant app. `backend/` and `frontend/` live here
because the Supervisor builds an app with its own directory as the Docker build
context - it cannot reach files above it.

The directory is still called `addon/`, and the manifest is still `config.yaml`
alongside a root `repository.yaml`. Home Assistant 2026.2 renamed add-ons to
apps in the interface and the documentation only; the file names, the `/addons`
folder, the slug and the Supervisor APIs were deliberately left unchanged.
