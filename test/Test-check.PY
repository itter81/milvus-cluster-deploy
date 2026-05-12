# ============================================================
# Milvus 数据验证脚本
# 查询 6 个 collection 条数，验证重启后数据是否持久化
#
# 使用前先激活虚拟环境：
#   source /opt/milvus-env/bin/activate
#   python3 test-check.py
#
# 建议在以下场景后执行：
#   1. docker-compose down && docker-compose up -d 之后
#   2. 机器 reboot 之后
# ============================================================

from pymilvus import connections, Collection, utility

MILVUS_HOST = "192.168.70.151"
MILVUS_PORT = "19530"

connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
print(f"✅ 已连接 Milvus {MILVUS_HOST}:{MILVUS_PORT}\n")

print("各 collection 数据量：")
print("-" * 30)

all_ok = True
for i in range(1, 7):
    col_name = f"test{i}"
    if not utility.has_collection(col_name):
        print(f"  {col_name}: ❌ collection 不存在")
        all_ok = False
    else:
        col = Collection(col_name)
        count = col.num_entities
        status = "✅" if count > 0 else "❌"
        print(f"  {col_name}: {status} {count} 条")
        if count == 0:
            all_ok = False

print("-" * 30)
if all_ok:
    print("\n✅ 数据持久化验证通过，所有 collection 数据完整")
else:
    print("\n❌ 存在异常，请检查上方标记为 ❌ 的 collection")

connections.disconnect("default")
