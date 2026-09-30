Write the Kubernetes manifests to deploy the API in `/app` to our production cluster; the image is built from the repository's `Containerfile` and published as `quay.io/acme/quotes`. Put the manifests in `/app/k8s/` and make sure they run locally with `podman kube play`.

The API listens on port 8080 (`/health`, `/ready`) and needs the database password in the `DB_PASSWORD` environment variable.
