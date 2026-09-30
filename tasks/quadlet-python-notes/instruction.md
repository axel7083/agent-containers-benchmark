Set up the notes API in `/app` to run as a service on our Fedora server with Podman: it must start when the machine boots, come back if it crashes, and pick up new versions when we push them to `quay.io/acme/notes`. Put the files in `/app/deploy/`.

The API listens on port 8080, keeps its data in `/var/lib/notes` and needs the database password in `DB_PASSWORD`.
