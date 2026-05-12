# ============================================================
# Milvus 写入测试脚本
# 创建 6 个 collection，每个随机写入 1w-2w 条数据并落盘
#
# 使用前先激活虚拟环境：
#   source /opt/milvus-env/bin/activate
#   python3 test-write.py
# ============================================================

import random
from pymilvus import connections, FieldSchema, CollectionSchema, DataType, Collection, utility

MILVUS_HOST = "192.168.70.151"
MILVUS_PORT = "19530"
DIM = 128

connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
print(f"✅ 已连接 Milvus {MILVUS_HOST}:{MILVUS_PORT}\n")

for i in range(1, 7):
    col_name = f"test{i}"
    num = random.randint(10000, 20000)

    print(f"[{col_name}] 准备写入 {num} 条数据...")

    # 已存在先删掉
    if utility.has_collection(col_name):
        utility.drop_collection(col_name)
        print(f"[{col_name}] 已删除旧 collection")

    # 定义 schema
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="vec", dtype=DataType.FLOAT_VECTOR, dim=DIM),
        FieldSchema(name="info", dtype=DataType.VARCHAR, max_length=256),
    ]
    schema = CollectionSchema(fields=fields, description=f"{col_name} test collection")
    col = Collection(name=col_name, schema=schema)

    # 分批插入，每批 1000 条
    batch_size = 1000
    inserted = 0
    while inserted < num:
        current_batch = min(batch_size, num - inserted)
        vecs = [[random.random() for _ in range(DIM)] for _ in range(current_batch)]
        infos = [f"{col_name}_row_{inserted + j}" for j in range(current_batch)]
        col.insert([vecs, infos])
        inserted += current_batch

    # flush 落盘
    col.flush()
    print(f"[{col_name}] ✅ 写入完成，落盘条数: {col.num_entities}\n")

print("=" * 50)
print("全部写入完成，各 collection 数据量汇总：")
for i in range(1, 7):
    col = Collection(f"test{i}")
    print(f"  test{i}: {col.num_entities} 条")

connections.disconnect("default")
print("\n✅ 完成，可执行以下操作验证持久化：")
print("  1. docker-compose down && docker-compose up -d  → 再跑 test-check.py")
print("  2. reboot                                       → 再跑 test-check.py")
