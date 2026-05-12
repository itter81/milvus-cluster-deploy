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
└── scripts/
    └── start-milvus.sh          # 主节点启动脚本（含 pulsar 自动初始化）
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

# 清理数据
# ⚠️ pulsar 必须整个目录删，不能只删内容
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

## 开发接入信息 | Developer Access

| Item | Value |
| --- | --- |
| Milvus 连接地址 | `192.168.70.151:19530` |
| 管理界面 | http://192.168.70.150:8000 |
| 限流 | 2000 QPS / burst 4000 |
| QueryNode 数量 | 5（151/152/153/154/155） |

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
# 主节点
- /opt/milvus/milvus-151.yaml:/milvus/configs/milvus.yaml

# 扩展节点
- /opt/milvus/milvus.yaml:/milvus/configs/milvus.yaml
```

> ⚠️ 复制配置到新节点时，文件名和挂载路径必须同步修改

---

### 4. milvus.yaml 不能有重复 key

**现象：** 追加配置后出现两个 `proxy` 或 `queryNode` 块，后者覆盖前者导致配置丢失

**解法：** 修改配置用 `cat >` 整体重写，不要用 `>>` 追加

---

## Author

**安栋梁 (An Dongliang)** Infrastructure & AI Ops Engineer | RHCE · HCIE · KYCP

---

## License

MIT
