# Kubernetes manifests

The `quotes-db` Secret is deliberately not in this repository. Create it before the first deploy:

```sh
kubectl create secret generic quotes-db --from-file=password=/dev/stdin
kubectl apply -f k8s/
```
