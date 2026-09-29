The container for the API in `/app` does not work: the image builds, but `podman run` exits right away. Fix it so the image builds and runs with Podman.

The API listens on port 8080 and answers `GET /health`.
