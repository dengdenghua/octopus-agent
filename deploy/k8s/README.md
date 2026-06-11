# Kubernetes 部署

最小可用的 k8s 清单 · 一键 apply：

```bash
kubectl apply -k deploy/k8s/          # 用 kustomize 按顺序 apply
# 或逐个 apply：
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml   # 先按说明填值
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/redis.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/ingress.yaml  # 可选 · 按你的 ingress-controller
```

## 资源设定（MVP）

| 对象 | replicas | CPU req / limit | Mem req / limit | 备注 |
|---|---|---|---|---|
| `octopus-agent` | 1（可以 2+）| 100m / 500m | 256Mi / 1Gi | 多 replica 靠 RedisCoordinator 协调 |
| `redis` | 1 | 50m / 200m | 64Mi / 256Mi | 生产请接管到 Redis Sentinel / Cluster |

## HA 拓扑

- `replicas: 2+` 时 · agent 之间用 `RedisCoordinator` 做 leader 选举
- 反思 / 调度类单点任务自动由 leader 跑 · 其他副本做请求处理
- leader 挂掉 · lease 过期后其他副本自动接管（ttl 默认 30s）

## 接进来的改造

- 把 `Deployment.spec.template.spec.containers[0].image` 改成自建 registry
- `Secret` 填真 API key · 或用 ExternalSecrets/AWS Secret Manager
- `Ingress` host 改成你的域名 · tls 用 cert-manager

## 卸载

```bash
kubectl delete -k deploy/k8s/
```
