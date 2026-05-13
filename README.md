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

## 仓库结构 | Repository Structure

```
milvus-cluster-deploy/
├── README.md                    # 本文档
├── master/
│   ├── docker-compose.yml       # 主节点编排文件
│   └── milvus-151.yaml          # 主节点 Milvus 配置
├── querynode/
│   ├── docker-compose.yml       # 扩展节点编排文件（152-155 通用）
│   └── milvus.yaml              # 扩展节点配置模板（只需改 IP）
├── scripts/
│   └── start-milvus.sh          # 主节点启动脚本（含 pulsar 自动初始化）
└── test/
    └── write_test_data.py       # 写入测试数据脚本（含 flush 验证）
```

---

## 部署步骤 | Deployment

### 主节点（192.168.70.151）

```bash
# 1. 创建目录并授权
mkdir -p /data/etcd/data /data/minio/data \
         /data/milvus/rootcoord /data/milvus/proxy \
         /data/milvus/querycoord /data/milvus/querynode \
         /data/milvus/indexcoord /data/milvus/indexnode \
         /data/milvus/datacoord /data/milvus/datanode
chmod -R 777 /data

# 2. 复制配置文件
cp master/docker-compose.yml /opt/milvus/docker-compose.yml
cp master/milvus-151.yaml /opt/milvus/milvus-151.yaml
cp scripts/start-milvus.sh /opt/milvus/start-milvus.sh

# 3. 启动（使用脚本，会自动处理 pulsar 初始化）
bash /opt/milvus/start-milvus.sh
```

### 扩展节点（192.168.70.152-155）

```bash
# 1. 创建目录并授权
mkdir -p /data/milvus/querynode
chmod -R 777 /data

# 2. 复制配置文件
cp querynode/docker-compose.yml /opt/milvus/docker-compose.yml
cp querynode/milvus.yaml /opt/milvus/milvus.yaml

# 3. 修改 milvus.yaml 中的 queryNode.ip 为本机 IP
vi /opt/milvus/milvus.yaml

# 4. 启动（等主节点完全就绪后再执行）
cd /opt/milvus && docker-compose up -d
```

> ⚠️ 扩展节点必须在主节点完全就绪（约 2 分钟）后再启动

---

## 清理数据重建 | Clean Rebuild

```bash
# 停容器
cd /opt/milvus && docker-compose down

# ⚠️ MinIO 和 etcd 必须同时清，单独清一个会导致数据不一致
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

## 数据持久化验证 | Data Persistence Verification

> ⚠️ 写入数据后，必须确认数据已 flush 到 MinIO，再做重启测试。Attu 显示有数据不等于已持久化。

```bash
# 写入数据后立刻执行 flush（在有 pymilvus 的机器上执行）
python3 -c "
from pymilvus import connections, Collection, utility
connections.connect(host='192.168.70.151', port='19530')
for name in utility.list_collections():
    col = Collection(name)
    col.flush()
    print(name, 'flushed', col.num_entities)
"

# 等待约 1 分钟，确认 MinIO 有文件后再重启
ssh root@192.168.70.151 "du -sh /data/minio/data/a-bucket/files/"
# 输出不为 0 才说明数据已持久化
```

**数据流向说明：**

```
写入 → Pulsar（消息队列）→ DataNode 异步 flush → MinIO（持久化）
```

- 写入成功只代表数据进了 Pulsar，不代表已写入 MinIO
- 重启后 Milvus 会从 Pulsar 重放消息恢复数据，但 Pulsar 数据有保留时间限制
- 只有 flush 到 MinIO 的数据才是真正持久化的

---

## 开发接入信息 | Developer Access

| Item | Value |
| --- | --- |
| Milvus 连接地址 | `192.168.70.151:19530` |
| 管理界面 | http://192.168.70.150:8000 |
| 限流 | 2000 QPS / burst 4000 |
| QueryNode 数量 | 5（151/152/153/154/155） |

---

## Key Findings

### 1. 必须使用 v2.4.13-hotfix，不能用 v2.4.13

**现象：** 重启后 rootcoord 日志显示 `collections recovered from db [collection_num=0]`，Attu 里 collection 全部消失

**根因：** v2.4.13 存在已知 bug：如果 MetaKV 快照被垃圾回收，重启后 rootcoord 无法从 etcd 恢复 collection 信息。频繁重启或 etcd 压缩后必然触发。

**解法：** 使用官方 hotfix 版本 `milvusdb/milvus:v2.4.13-hotfix`，该版本修复了此问题

---

### 2. 多 IP 机器必须在 milvus.yaml 写死 IP 和端口

**现象：** querynode 注册到 etcd 的 Address 是错误的 IP（如 `192.167.70.152` 而不是 `192.168.70.152`），导致 querycoord 无法连接，collection 加载卡在 33%/50%

**根因：** Milvus 默认选择第一个可用的单播地址，多网卡机器可能选错。注释原文：`If not specified, use the first unicastable address`

**解法：** 在 milvus.yaml 中明确指定：

```yaml
queryNode:
  ip: 192.168.70.152   # 填写正确的宿主机 IP
  port: 21123
```

**验证方法：**

```bash
# 检查 querynode 注册的 IP 是否正确
docker exec milvus-etcd etcdctl \
  --endpoints=http://192.168.70.151:2379 \
  get --prefix by-dev/meta/session/querynode --keys-only
```

---

### 3. MinIO 与 etcd 数据必须同时清，不能单独清一方

**现象：** 只清 MinIO 保留 etcd，datanode 一直报 `key not found`，无法 flush 新数据；只清 etcd 保留 MinIO，collection 元数据丢失

**根因：** etcd 存储 segment 元数据，指向 MinIO 的具体文件路径。两者不一致时，datanode 找不到文件或 rootcoord 读不到 collection

**解法：** 清数据必须同时清 MinIO 和 etcd，参考「清理数据重建」章节

---

### 4. Pulsar 删数据重启后 tenant 不自动创建

**现象：** rootcoord 持续报 `MetadataError`，proxy 无法就绪

**根因：** pulsar standalone 只在数据目录**不存在**时才初始化 `public` tenant/namespace。删数据后目录还在（哪怕是空的），pulsar 认为不是首次启动，跳过初始化。

**解法：** 使用 `start-milvus.sh`，启动后自动检测并创建 tenant

---

### 5. Pulsar 容器权限问题

**现象：** pulsar 容器持续重启，日志报 `AccessDeniedException: /pulsar/data/standalone`

**根因：** docker 创建挂载目录时权限不足，pulsar 容器内用户无写权限

**解法：** docker-compose.yml 中给 pulsar 加 `user: root`

```yaml
pulsar:
  user: root
```

---

### 6. 配置文件命名规范

**规范：** 主节点配置文件按 IP 命名，docker-compose.yml 中挂载路径必须对应

```yaml
# 主节点
- /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml

# 扩展节点
- /opt/milvus/milvus.yaml:/milvus/configs/milvus.yaml
```

> ⚠️ 复制配置到新节点时，文件名和挂载路径必须同步修改

---

### 7. milvus.yaml 不能有重复 key

**现象：** 追加配置后出现两个 `proxy` 或 `queryNode` 块，后者覆盖前者导致配置丢失

**解法：** 修改配置用 `cat >` 整体重写，不要用 `>>` 追加

---

### 8. 主节点各组件端口对照表

| 组件 | 端口 | 说明 |
| --- | --- | --- |
| etcd | 2379 | 元数据存储 |
| pulsar | 6650 | 消息队列 |
| minio | 9000/9001 | 对象存储/控制台 |
| rootcoord | 53100 | 根协调器 |
| proxy | 19530/19529 | 接入层/内部通信 |
| querycoord | 19531 | 查询协调器 |
| querynode | 21123 | 查询节点 |
| indexcoord | 31000 | 索引协调器 |
| indexnode | 21121 | 索引节点 |
| datacoord | 13333 | 数据协调器 |
| datanode | 21124 | 数据节点 |

> ⚠️ v2.4.13 中 indexcoord 已合并到 datacoord，两者共用 13333 端口，属正常现象

---

## Author

**安栋梁 (An Dongliang)** Infrastructure & AI Ops Engineer | RHCE · HCIE · KYCP

---

## License

MIT
