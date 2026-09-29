`/app/site` contains a static website. Package it as a container image that serves the site over HTTP, so it can be built and run with Podman.

The container must serve the site on port 8080 (`/health` is one of the static files).
