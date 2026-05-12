#!/bin/bash

# ============================================================
# Milvus 集群启动脚本
# 自动处理 pulsar tenant 初始化问题
# 使用方式: bash /opt/milvus/scripts/start-milvus.sh
# ============================================================

MILVUS_DIR="/opt/milvus"
PULSAR_HOST="192.168.70.151"   # 主节点 IP，如需修改请改这里

cd $MILVUS_DIR

echo "=== [1/4] 启动所有容器 ==="
docker-compose up -d

echo "=== [2/4] 等待 pulsar 就绪 ==="
MAX_WAIT=120
WAITED=0
until docker exec milvus-pulsar bin/pulsar-admin clusters list > /dev/null 2>&1; do
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo "❌ pulsar 等待超时，请检查容器状态"
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
