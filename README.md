# milvus-cluster-deploy

Milvus 分布式集群部署实践 | Milvus Distributed Cluster Deployment

---

## 背景 | Background

Milvus 官方推荐使用 Kubernetes + Milvus Operator 部署集群，但本项目场景为：

- 节点数量少（5个），引入 K8s **运维成本**远大于收益
- 离线环境，K8s 镜像依赖复杂
- 业务方只需要一套稳定可用的向量数据库，不需要弹性伸缩

因此选择 **docker-compose 手工部署**，每台机器独立管理，配置透明，出问题直接看容器日志定位。

> 如果后续节点数量扩展到 10+ 或需要弹性伸缩，建议迁移到 K8s + Milvus Operator 方案。

---

## 节点规划 | Node Planning

| IP | 角色 | 说明 |
| --- | --- | --- |
| 192.168.70.150 | Attu 管理界面 | Web 可视化管理，访问地址 http://192.168.70.150:8000 |
| 192.168.70.151 | 主节点 | etcd / pulsar / minio / 全部 coord + node |
| 192.168.70.152 | QueryNode | 扩展查询节点 |
| 192.168.70.153 | QueryNode | 扩展查询节点 |
| 192.168.70.154 | QueryNode | 扩展查询节点 |
| 192.168.70.155 | QueryNode | 扩展查询节点 |

---

## 环境要求 | Requirements

| Item | Version |
| --- | --- |
| CPU | 64 Core |
| Memory | 62GB+ |
| Disk(/data) | 4.7T+ |
| Docker | 20.10+ |
| docker-compose | v2.x |
| Milvus | v2.4.13-hotfix |
| Pulsar | 2.10.4 |
| MinIO | RELEASE.2023-03-13T19-46-17Z |
| etcd | v3.5.5 |

---

## 目录结构 | Directory Structure

```
/opt/milvus/
├── docker-compose.yml        # 编排文件
├── milvus-151.yaml           # 主节点配置（按 IP 命名）
└── milvus.yaml               # QueryNode 配置（152-155 各自 IP 不同）

/data/
├── etcd/data                 # etcd 数据
├── pulsar/                   # pulsar 数据（整个目录，非 /data/pulsar/data）
├── minio/data                # minio 数据
└── milvus/                   # 各组件数据
    ├── rootcoord/
    ├── proxy/
    ├── querycoord/
    ├── querynode/
    ├── indexcoord/
    ├── indexnode/
    ├── datacoord/
    └── datanode/
```

---

## 主节点配置 | Master Node（192.168.70.151）

### docker-compose.yml

```yaml
version: '3.5'
services:
  etcd:
    container_name: milvus-etcd
    image: quay.io/coreos/etcd:v3.5.5
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=10737418240
      - ETCD_SNAPSHOT_COUNT=50000
    volumes:
      - /data/etcd/data:/etcd
    command: etcd -advertise-client-urls=http://192.168.70.151:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    ports:
      - "2379:2379"
      - "12379:2379"

  pulsar:
    container_name: milvus-pulsar
    user: root
    image: apachepulsar/pulsar:2.10.4
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    volumes:
      - /data/pulsar/data:/pulsar/data
    environment:
      - nettyMaxFrameSizeBytes=104867840
      - defaultRetentionTimeInMinutes=10080
      - defaultRetentionSizeInMB=51200
      - PULSAR_PREFIX_maxMessageSize=104857600
      - PULSAR_GC=-XX:+UseG1GC
      - PULSAR_PREFIX_advertisedAddress=192.168.70.151
    ports:
      - "6650:6650"
    command: |
      /bin/bash -c \
      "bin/apply-config-from-env.py conf/standalone.conf && \
      exec bin/pulsar standalone --no-functions-worker --no-stream-storage"

  minio:
    container_name: milvus-minio
    image: minio/minio:RELEASE.2023-03-13T19-46-17Z
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    volumes:
      - /data/minio/data:/minio_data
    command: minio server /minio_data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

  rootcoord:
    container_name: milvus-rootcoord
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "rootcoord"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
      ROOT_COORD_ADDRESS: 192.168.70.151:53100
    volumes:
      - /data/milvus/rootcoord:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "53100:53100"
    depends_on:
      - etcd
      - pulsar
      - minio

  proxy:
    container_name: milvus-proxy
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "proxy"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
    volumes:
      - /data/milvus/proxy:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "19530:19530"
      - "9091:9091"
      - "19529:19529"

  querycoord:
    container_name: milvus-querycoord
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "querycoord"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
      QUERY_COORD_ADDRESS: 192.168.70.151:19531
    volumes:
      - /data/milvus/querycoord:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "19531:19531"
    depends_on:
      - etcd
      - pulsar
      - minio

  querynode:
    container_name: milvus-querynode
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "querynode"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
    volumes:
      - /data/milvus/querynode:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "21123:21123"
    depends_on:
      - querycoord

  indexcoord:
    container_name: milvus-indexcoord
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "indexcoord"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
      INDEX_COORD_ADDRESS: 192.168.70.151:31000
    volumes:
      - /data/milvus/indexcoord:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "31000:31000"
    depends_on:
      - etcd
      - pulsar
      - minio

  indexnode:
    container_name: milvus-indexnode
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "indexnode"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
      INDEX_COORD_ADDRESS: 192.168.70.151:31000
    volumes:
      - /data/milvus/indexnode:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "21121:21121"
    depends_on:
      - indexcoord

  datacoord:
    container_name: milvus-datacoord
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "datacoord"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
      DATA_COORD_ADDRESS: 192.168.70.151:13333
    volumes:
      - /data/milvus/datacoord:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "13333:13333"
    depends_on:
      - etcd
      - pulsar
      - minio

  datanode:
    container_name: milvus-datanode
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "datanode"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
    volumes:
      - /data/milvus/datanode:/var/lib/milvus
      - /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml
    ports:
      - "21124:21124"
    depends_on:
      - datacoord

networks:
  default:
    name: milvus
```

### milvus-151.yaml

```yaml
localStorage:
  path: /var/lib/milvus/data/

rootCoord:
  ip: 192.168.70.151
  port: 53100

proxy:
  ip: 192.168.70.151
  port: 19530
  internalPort: 19529
  rateLimiter:
    enabled: true
    limit: 2000
    burst: 4000

queryCoord:
  ip: 192.168.70.151
  port: 19531

queryNode:
  ip: 192.168.70.151
  port: 21123
  localStorage:
    size: 32212254720

indexCoord:
  ip: 192.168.70.151
  port: 31000

indexNode:
  ip: 192.168.70.151
  port: 21121

dataCoord:
  ip: 192.168.70.151
  port: 13333

dataNode:
  ip: 192.168.70.151
  port: 21124
```

---

## 扩展节点配置 | QueryNode（192.168.70.152）

### docker-compose.yml

> ⚠️ 152/153/154/155 的 docker-compose.yml 完全一样，无需修改

```yaml
version: '3.5'
services:
  querynode:
    network_mode: host
    container_name: milvus-querynode
    image: milvusdb/milvus:v2.4.13-hotfix
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "500m"
        max-file: "3"
    command: ["milvus", "run", "querynode"]
    environment:
      ETCD_ENDPOINTS: 192.168.70.151:2379
      MINIO_ADDRESS: 192.168.70.151:9000
      PULSAR_ADDRESS: pulsar://192.168.70.151:6650
      QUERY_COORD_ADDRESS: 192.168.70.151:19531
      DATA_COORD_ADDRESS: 192.168.70.151:13333
      ROOT_COORD_ADDRESS: 192.168.70.151:53100
      INDEX_COORD_ADDRESS: 192.168.70.151:31000
    volumes:
      - /data/milvus/querynode:/var/lib/milvus
      - /opt/milvus/milvus.yaml:/milvus/configs/milvus.yaml
```

### milvus.yaml

> ⚠️ 每个节点只需要把 `queryNode.ip` 改成自己的 IP，其余完全一样

```yaml
# 192.168.70.152
localStorage:
  path: /var/lib/milvus/data/

queryNode:
  ip: 192.168.70.152
  port: 21123
  localStorage:
    size: 32212254720

---

# 192.168.70.153
localStorage:
  path: /var/lib/milvus/data/

queryNode:
  ip: 192.168.70.153
  port: 21123
  localStorage:
    size: 32212254720

---

# 192.168.70.154
localStorage:
  path: /var/lib/milvus/data/

queryNode:
  ip: 192.168.70.154
  port: 21123
  localStorage:
    size: 32212254720

---

# 192.168.70.155
localStorage:
  path: /var/lib/milvus/data/

queryNode:
  ip: 192.168.70.155
  port: 21123
  localStorage:
    size: 32212254720
```

---

## 启动顺序 | Startup Order

```bash
# 第一步：初始化数据目录并授权（首次部署执行）
mkdir -p /data/etcd/data /data/minio/data \
         /data/milvus/rootcoord /data/milvus/proxy \
         /data/milvus/querycoord /data/milvus/querynode \
         /data/milvus/indexcoord /data/milvus/indexnode \
         /data/milvus/datacoord /data/milvus/datanode
chmod -R 777 /data

# 第二步：启动主节点（192.168.70.151）
cd /opt/milvus && bash start-milvus.sh

# 第三步：等待主节点完全就绪（约 2 分钟），再启动扩展节点
for i in 152 153 154 155; do
  ssh root@192.168.70.$i "cd /opt/milvus && docker-compose up -d"
done
```

> ⚠️ 扩展节点必须在主节点完全就绪后再启动，否则 querycoord 注册失败

---

## 清理数据重建 | Clean Rebuild

```bash
# 停容器
cd /opt/milvus && docker-compose down

# 清理数据
# ⚠️ pulsar 必须整个目录删，不能只删内容，否则 tenant 不会自动初始化
rm -rf /data/pulsar
rm -rf /data/etcd/data/*
rm -rf /data/minio/data/*
rm -rf /data/milvus/rootcoord/* /data/milvus/proxy/* \
       /data/milvus/querycoord/* /data/milvus/querynode/* \
       /data/milvus/indexcoord/* /data/milvus/indexnode/* \
       /data/milvus/datacoord/* /data/milvus/datanode/*

# 重新授权
chmod -R 777 /data

# 重新启动
bash /opt/milvus/start-milvus.sh
```

---

## 启动脚本 | start-milvus.sh

> 解决 pulsar 删数据重启后 tenant 不自动创建的问题，每次启动用此脚本代替 `docker-compose up -d`

```bash
#!/bin/bash

MILVUS_DIR="/opt/milvus"
PULSAR_HOST="192.168.70.151"

cd $MILVUS_DIR

echo "=== [1/4] 启动所有容器 ==="
docker-compose up -d

echo "=== [2/4] 等待 pulsar 就绪 ==="
MAX_WAIT=120
WAITED=0
until docker exec milvus-pulsar bin/pulsar-admin clusters list > /dev/null 2>&1; do
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo "❌ pulsar 等待超时"
    exit 1
  fi
  echo "  等待 pulsar 启动... (${WAITED}s)"
  sleep 5
  WAITED=$((WAITED + 5))
done
echo "  ✅ pulsar 已就绪"

echo "=== [3/4] 检查并初始化 pulsar tenant/namespace ==="
if ! docker exec milvus-pulsar bin/pulsar-admin tenants get public > /dev/null 2>&1; then
  echo "  public tenant 不存在，开始初始化..."
  docker exec milvus-pulsar bin/pulsar-admin clusters create standalone \
    --broker-url pulsar://${PULSAR_HOST}:6650 \
    --url http://${PULSAR_HOST}:8080 > /dev/null 2>&1 || true
  docker exec milvus-pulsar bin/pulsar-admin tenants create public \
    --allowed-clusters standalone
  docker exec milvus-pulsar bin/pulsar-admin namespaces create public/default
  docker exec milvus-pulsar bin/pulsar-admin namespaces create public/functions
  echo "  ✅ pulsar 初始化完成"

  echo "=== [4/4] 重启 rootcoord ==="
  docker restart milvus-rootcoord
  echo "  ✅ rootcoord 已重启"
else
  echo "  ✅ public tenant 已存在，跳过初始化"
  echo "=== [4/4] 跳过重启 rootcoord ==="
fi

echo ""
echo "=== 完成，等待各组件就绪约 1-2 分钟 ==="
```

---

## Key Findings

### 1. Pulsar 删数据重启后 tenant 不自动创建

**现象：** rootcoord 持续报 `MetadataError`，proxy 无法就绪

**根因：** pulsar standalone 只在数据目录**不存在**时才初始化 `public` tenant/namespace。删数据后目录还在（哪怕是空的），pulsar 认为不是首次启动，跳过初始化。

**解法：** 使用 `start-milvus.sh`，启动后自动检测并创建 tenant

---

### 2. Pulsar 容器权限问题

**现象：** pulsar 容器持续重启，日志报 `AccessDeniedException: /pulsar/data/standalone`

**根因：** docker 创建挂载目录时权限不足，pulsar 容器内用户无写权限

**解法：** docker-compose.yml 中给 pulsar 加 `user: root`

```yaml
pulsar:
  user: root
```

---

### 3. 配置文件命名规范

**规范：** 主节点配置文件按 IP 命名，docker-compose.yml 中挂载路径必须对应

```yaml
# 主节点挂载
- /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml

# 扩展节点挂载
- /opt/milvus/milvus.yaml:/milvus/configs/milvus.yaml
```

> ⚠️ 复制配置到新节点时，文件名和挂载路径必须同步修改，否则容器读到的是旧配置

---

### 4. milvus.yaml 不能有重复 key

**现象：** 追加配置后出现两个 `proxy` 或 `queryNode` 块，后者覆盖前者导致配置丢失

**解法：** 修改配置用 `cat >` 整体重写，不要用 `>>` 追加

---

## 开发接入信息 | Developer Access

| Item | Value |
| --- | --- |
| Milvus 连接地址 | `192.168.70.151:19530` |
| 管理界面 | http://192.168.70.150:8000 |
| 限流 | 2000 QPS / burst 4000 |
| QueryNode 数量 | 5（151/152/153/154/155） |

---

## Author

**安栋梁 (An Dongliang)** Infrastructure & AI Ops Engineer | RHCE · HCIE · KYCP

---

## License

MIT
