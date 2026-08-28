# Mesh Sentinel add-on

Build context for the Home Assistant add-on. `backend/` and `frontend/` live
here because the Supervisor builds an add-on with its own directory as the
Docker build context - it cannot reach files above it.
