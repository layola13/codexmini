# sa_plugin_db 调用指南（for scodex-mini 会话持久化）

> 依据：`~/projects/sa_plugins/sa_plugin_db` 源码（`db.sai` / `db.sal` / `src/db_saasm_api.zig` / `src/table.zig` / `src/schema.zig`）
> + 真实 `.sla` 端到端实测（`sa sla build-exe --release-fast` 编译，`./probe` 运行，全部 PASS）。
> 插件位置：`~/.local/share/sa_plugins/installed/db/current/`（`libdb.so`，符号按 `sa_db_` 前缀解析）。
> `.sla` 用法：`@import "plugin_abi/db.sai"`（对照 `http.sla` 的 `@import "plugin_abi/sa_http_client.sai"`），
> 错误码常量来自 `@import "plugin_abi/db.sal"`（`SA_DB_OK` 等 `#def`）。

## 0. 调用约定（已实测）

- `.sai` 里 `&x: ptr` 的 **IN** 参数：直接传 ptr 值（如 `STR_PTR("sessions")`、结构体 `&srow`）。
- **OUT** 参数（`&out_*: ptr`）：传 `&var`，`var` 用 `let`/`var` 预先绑定。
- 返回值 `u32` 即状态码；`0 = SA_DB_OK`。
- `.sla` 没有定长数组类型：行缓冲、行号数组、info 结构体都用 **全 u64 字段的 struct** 表达，
  `&s` 传进去，内存布局是声明顺序 packed（`u64` 无 padding，已用 round-trip 实测验证）。
- `let` 单次赋值；`i64 -> u64` 可隐式转换（`let u: u64 = ms;` 编译通过）。

## 1. 错误码（`db.sal` 的 `#def`，与 zig 源码 `SA_DB_*` 一致）

| 值 | 常量 | 含义 |
|----|------|------|
| 0 | `SA_DB_OK` | 成功 |
| 1 | `SA_DB_ERR_INVALID_ARGUMENT` | 空指针 / 长度为 0 的 out 缓冲 / 越界 column_index 等 |
| 2 | `SA_DB_ERR_INVALID_FORMAT` | schema 非法 / 行长度≠表行宽 / **缺少所需的 index** / blob store 名非法 |
| 3 | `SA_DB_ERR_NOT_FOUND` | 按 key 取行未命中 |
| 4 | `SA_DB_ERR_LOCKED` | 表被 lock |
| 5 | `SA_DB_ERR_CURSOR_OVERFLOW` | 游标溢出 |
| 6 | `SA_DB_ERR_VERIFY_FAILED` | 校验失败 |
| 7 | `SA_DB_ERR_OUT_OF_MEMORY` | 内存不足 |
| 8 | `SA_DB_ERR_IO` | IO 错误 |
| 9 | `SA_DB_ERR_CONSTRAINT` | 唯一约束冲突 |

## 2. Schema（`sa_db_init_schema` 的 schema_source）

```rust
@extern sa_db_init_schema(&root: ptr, root_len: u64,
    &schema_path: ptr, schema_path_len: u64,   // 如 "sessions.sadb-schema"；表名 = 去掉扩展名的 basename
    &schema_source: ptr, schema_source_len: u64, // DDL 文本（字节）
    &out_info: ptr) -> u32                     // SaDbTableInfo（32 字节，见下）
```

DDL 格式（逐行 `#def`，`//` 注释）：

```text
#def MAX_ROWS = 1024
#def COL_ID_STRIDE = 8 // u64
#def COL_CREATED_MS_STRIDE = 8 // u64
#def COL_UPDATED_MS_STRIDE = 8 // u64
#def COL_MSG_COUNT_STRIDE = 8 // u64
#def COL_TITLE_BLOB_STRIDE = 8 // blob_handle
```

- `MAX_ROWS` 必填；每列一个 `COL_<NAME>_STRIDE`，列名 = `<NAME>` 原样（大小写保留），列顺序 = 声明顺序（column_index 0-based）。
- 列类型写在行尾注释里：`// u64`（stride 8）是最常用的；**blob 引用的列必须写 `// blob_handle`**
  （stride 8，存的是 blob id，见 §4）。插件另有 `u32`/`i64`/`f32`/`bool` 等 stride 类型，本指南只用 u64/blob_handle。
- `schema_source_len` 单位是**字节**。

sessions / messages 完整 DDL（可直接用）：

```text
# sessions.sadb-schema
#def MAX_ROWS = 1024
#def COL_ID_STRIDE = 8 // u64
#def COL_CREATED_MS_STRIDE = 8 // u64
#def COL_UPDATED_MS_STRIDE = 8 // u64
#def COL_MSG_COUNT_STRIDE = 8 // u64
#def COL_TITLE_BLOB_STRIDE = 8 // blob_handle
```

```text
# messages.sadb-schema
#def MAX_ROWS = 65536
#def COL_SESSION_ID_STRIDE = 8 // u64
#def COL_SEQ_STRIDE = 8 // u64
#def COL_ROLE_STRIDE = 8 // u64
#def COL_BODY_BLOB_STRIDE = 8 // blob_handle
```

`SaDbTableInfo`（out_info，32 字节，字段顺序）：

```sla
struct DbTableInfo {
    row_count: u64,      // +0
    segment_count: u64,  // +8
    epoch: u64,          // +16
    locked: u64,         // +24，0/1
}
```

实测结论：
- **root 目录不存在会自动创建**（含多级父目录，`makePath`）。`root` 传 `""`/空串等价于 `"."`（cwd）。
- **`init_schema` 不是幂等的**：对已存在的表再次调用会**清空重建**（实测重建后 `row_count=0`，旧数据丢失）。
  启动逻辑应该是"表不存在才 init"，不要每次启动无条件 init。

```sla
let info = DbTableInfo { row_count: 0, segment_count: 0, epoch: 0, locked: 0 };
let st = sa_db_init_schema(root, root_len,
    STR_PTR("sessions.sadb-schema"), STR_LEN("sessions.sadb-schema"),
    schema_ptr, schema_len, &info);
// st == 0 且 info.row_count == 0 表示建表成功
```

## 3. 当前时间毫秒（给 created_ms / updated_ms）

`sa_std/time.sai`：

```rust
@extern sa_time_unix_ms() -> i64
```

```sla
@import "sa_std/time.sai"
let now_ms: i64 = sa_time_unix_ms();  // 实测 > 0
let now_u: u64 = now_ms;              // i64->u64 隐式转换，编译通过
```

## 4. Blob：存与取

```rust
@extern sa_db_blob_put(&root: ptr, root_len: u64,
    &table_name: ptr, table_name_len: u64,       // blob 挂在哪张表名下（如 "sessions"）
    &store_name: ptr, store_name_len: u64,       // store 名，见命名规则
    &value: ptr, value_len: u64,                // value_len 单位：字节
    &out_id: ptr, &out_info: ptr) -> u32
```

- `store_name` 规则（源码 `validateBlobStoreName`）：1~64 字节，仅 `[A-Za-z0-9_]`，否则 err 2。
  store 是**每表独立**的命名空间；同一表内不同列可共用一个 store（如都用 `"texts"`）。
- `value` ≤ 16MB，否则 err 2。
- **`out_id` 从 1 开始递增**（实测第一个 blob id=1）；每次 put 都追加新 id，**不去重**。
- 同一 store 下 title/body 都用 `sa_db_blob_put`，行里存返回的 id（u64）。

读回（有 open 的 read handle 时用 `_handle` 版；否则用非 handle 版，参数是 root+表名）：

```rust
@extern sa_db_blob_value_len_handle(handle: ptr,
    &store_name: ptr, store_name_len: u64, id: u64,
    &out_found: ptr, &out_len: ptr) -> u32              // out_len 单位：字节；found 0/1
@extern sa_db_blob_value_copy_handle(handle: ptr,
    &store_name: ptr, store_name_len: u64, id: u64,
    &out_buf: ptr, out_buf_len: u64,                    // out_buf_len 单位：字节
    &out_found: ptr, &out_written: ptr) -> u32          // out_written 单位：字节
```

实测：`len_handle` 先拿长度 → 按长度准备缓冲 → `copy_handle`；`written` 为实际写入字节数
（缓冲小了会被截断，只写 `min(len, out_buf_len)`，`found` 照样为 1——所以**先问长度再分配**）。

```sla
let blob_id: u64 = 0;
let bi = DbTableInfo { row_count: 0, segment_count: 0, epoch: 0, locked: 0 };
let st = sa_db_blob_put(root, root_len, STR_PTR("sessions"), STR_LEN("sessions"),
    STR_PTR("texts"), STR_LEN("texts"),
    STR_PTR("hello"), STR_LEN("hello"), &blob_id, &bi);
// st == 0, blob_id == 1
```

## 5. 插入行

```rust
@extern sa_db_insert_row(&root: ptr, root_len: u64,
    &table_name: ptr, table_name_len: u64,
    &row: ptr, row_len: u64,          // row_len 单位：字节，必须 == 表行宽
    &out_info: ptr) -> u32
```

- 行编码：按列顺序 packed 的**小端 u64**（x86_64 上 struct 全 u64 字段直接就是正确布局）。
- **`row_len` 单位是字节**，不是 u64 个数；sessions 行 = 5×8 = **40**，messages 行 = 4×8 = **32**。
  长度 ≠ 行宽 → err 2（实测）。
- **没有自增 id**：调用方自己算 `max(id列)+1`（见 §7 `sa_db_max_u64_handle`；空表 max 返回 0，首个 id 为 1）。
- 每次 insert 都是追加；`out_info.row_count` 为插入后的总行数。

```sla
struct SessionRow { id: u64, created_ms: u64, updated_ms: u64, msg_count: u64, title_blob: u64 }
struct MessageRow { session_id: u64, seq: u64, role: u64, body_blob: u64 }

let srow = SessionRow { id: 1, created_ms: now_u, updated_ms: now_u, msg_count: 0, title_blob: blob_id };
let ii = DbTableInfo { row_count: 0, segment_count: 0, epoch: 0, locked: 0 };
let st = sa_db_insert_row(root, root_len, STR_PTR("sessions"), STR_LEN("sessions"), &srow, 40, &ii);

let mrow = MessageRow { session_id: 1, seq: 0, role: 1, body_blob: body_id };
let st2 = sa_db_insert_row(root, root_len, STR_PTR("messages"), STR_LEN("messages"), &mrow, 32, &ii);
```

更新 session 的 `msg_count` / `updated_ms` 用 upsert（按 id 列匹配，命中则整行替换，未命中则插入；
`out_inserted` 1=插入 / 0=更新）：

```rust
@extern sa_db_upsert_row_u64_key(&root: ptr, root_len: u64,
    &table_name: ptr, table_name_len: u64,
    column_index: u64, expected: u64,      // 匹配列（如 id 列 0）与期望值
    &row: ptr, row_len: u64,               // 整行新内容，单位字节
    &out_inserted: ptr, &out_info: ptr) -> u32
```

## 6. 读路径

```rust
@extern sa_db_open_read_table(&root: ptr, root_len: u64,
    &table_name: ptr, table_name_len: u64, &out_handle: ptr) -> u32
@extern sa_db_close_read_table(handle: ptr) -> u32
@extern sa_db_snapshot_info_handle(handle: ptr, &out_info: ptr) -> u32
@extern sa_db_get_u64_handle(handle: ptr, column_index: u64, row_index: u64, &out_value: ptr) -> u32
@extern sa_db_get_row_handle(handle: ptr, row_index: u64, &out_row: ptr, out_row_len: u64) -> u32
```

`SaDbSnapshotInfo`（32 字节）：

```sla
struct DbSnapshotInfo {
    row_count: u64,     // +0  全表行数
    column_count: u64,  // +8
    row_bytes: u64,    // +16 表行宽（字节），get_row 缓冲必须 exactly 这么大
    epoch: u64,        // +24
}
```

**列出所有 session（全表扫描）**——实测通过：

```sla
let h: ptr = PTR_NULL();
sa_db_open_read_table(root, root_len, STR_PTR("sessions"), STR_LEN("sessions"), &h);
let si = DbSnapshotInfo { row_count: 0, column_count: 0, row_bytes: 0, epoch: 0 };
sa_db_snapshot_info_handle(h, &si);   // si.row_count == 1, si.row_bytes == 40

let i: u64 = 0;
let r = SessionRow { id: 0, created_ms: 0, updated_ms: 0, msg_count: 0, title_blob: 0 };
while i < si.row_count {
    sa_db_get_row_handle(h, i, &r, 40);  // out_row_len 单位：字节，必须 == row_bytes
    // r.id / r.title_blob ... 取到行后按需读 blob
    i = i + 1;
};
sa_db_close_read_table(h);
```

- `get_row_handle` 的行号是 0-based 物理行号；缓冲长度 ≠ row_bytes → err 2。
- 读完必须 `sa_db_close_read_table`（实测返回 0）。

## 7. 按 session_id 过滤 messages 并按 seq 排序

### 7.1 先建 pair index（必需）

```rust
@extern sa_db_create_u64_pair_index(&root: ptr, root_len: u64,
    &table_name: ptr, table_name_len: u64,
    column_index: u64, column_index2: u64,  // 这里是 (0=session_id, 1=seq)
    unique: u32,                            // 0=允许重复，1=唯一约束（冲突则 err 9）
    &out_info: ptr) -> u32
```

- **幂等**：已存在则跳过返回 0（源码 `indexExistsConflict`），启动时可无条件调用。
- **必须在 `open_read_table` 之前建**：实测建索引后，之前已 open 的 handle 调 filter 仍然 err，
  必须 close 后重新 open（snapshot 在 open 时固化）。
- 不建 index 直接调下面的 filter → **err 2**（实测）。

```sla
let ci = DbTableInfo { row_count: 0, segment_count: 0, epoch: 0, locked: 0 };
sa_db_create_u64_pair_index(root, root_len, STR_PTR("messages"), STR_LEN("messages"), 0, 1, 0, &ci);
```

### 7.2 filter：12 个参数精确语义

```rust
@extern sa_db_filter_u64_pair_key1_handle(handle: ptr,
    column_index: u64,    // pair index 的第一列（session_id 列 = 0）
    column_index2: u64,   // pair index 的第二列（seq 列 = 1）
    key1: u64,            // 要匹配的 session_id 值
    offset: u64,          // 分页偏移（跳过前 offset 个匹配行）
    limit: u64,           // 最多返回行数；0 = 返回 0 行（但 out_total 照常）
    &out_rows: ptr,       // 输出：u64 行号数组
    out_rows_len: u64,    // 单位：u64 元素个数（不是字节！）；0 → err 1
    &out_written: ptr,    // 实际写入的行号个数
    &out_total: ptr       // 匹配总行数（不受 offset/limit 影响）
) -> u32
```

- `out_rows` 返回的是**行号（row_index）数组**，可直接喂给 `sa_db_get_row_handle` / `sa_db_sort_rows_u64_handle`。
- 同一 `key1` 下，返回的行号**已按 key2（seq）升序**（pair index 按 (key1,key2,row) 排序，实测 seq 0,1,2 顺序返回）。
  所以"按 session 过滤 + 按 seq 排序"**一次 filter 就够**，不需要再 sort。
- `column_index2` 必须与建 index 时的第二列一致；两列都必须是 u64 列。

```sla
struct Rows8 { r0: u64, r1: u64, r2: u64, r3: u64, r4: u64, r5: u64, r6: u64, r7: u64 }

let mh: ptr = PTR_NULL();
sa_db_open_read_table(root, root_len, STR_PTR("messages"), STR_LEN("messages"), &mh);
let fr = Rows8 { r0: 0, r1: 0, r2: 0, r3: 0, r4: 0, r5: 0, r6: 0, r7: 0 };
let written: u64 = 0;
let total: u64 = 0;
// 查 session 1 的全部消息，按 seq 升序
let st = sa_db_filter_u64_pair_key1_handle(mh, 0, 1, 1, 0, 100, &fr, 8, &written, &total);
// st==0, written==3, total==3; fr.r0/r1/r2 是行号，对应 seq 0/1/2
let mr = MessageRow { session_id: 0, seq: 0, role: 0, body_blob: 0 };
sa_db_get_row_handle(mh, fr.r0, &mr, 32);  // seq == 0 的消息行
```

### 7.3 sort（无 index 时的备用 / 通用排序）

```rust
@extern sa_db_sort_rows_u64_handle(handle: ptr,
    column_index: u64,        // 按哪列的值排序（如 seq 列 = 1）
    &in_rows: ptr, in_rows_len: u64,   // 输入：u64 行号数组；in_rows_len 单位：u64 个数
    descending: u32,          // 0=升序，1=降序
    offset: u64, limit: u64,  // 对排序结果分页
    &out_rows: ptr, out_rows_len: u64, // 输出：排序后的行号数组；单位：u64 个数
    &out_written: ptr, &out_total: ptr) -> u32
```

- 语义：**对输入的行号数组按指定列的值排序**，返回新的行号数组。不需要预建 index（纯内存排序）。
- 实测：`in={2,0,1}` 按 seq 列升序 → `out={0,1,2}`，`written=3`。

### 7.4 取 max 做 id 分配

```rust
@extern sa_db_max_u64_handle(handle: ptr, column_index: u64, &out_max: ptr) -> u32
```

- 空表调 max：返回 0 且值为 0（实测）。所以新 id = `max_u64(id列) + 1`，空表首个 id 为 1。

## 8. 坑点汇总

1. **长度单位三套**，混了就 err 1/2：`row_len`/`out_row_len`/`value_len`/`out_buf_len`/`schema_source_len` 是**字节**；
   `out_rows_len`/`in_rows_len` 是 **u64 元素个数**。
2. **filter_u64_pair_key1 必须先 `sa_db_create_u64_pair_index`**，否则 err 2；且 index 要建在 open 之前，
   旧 handle 看不到后建的 index（必须重 open）。
3. **`init_schema` 非幂等**，重复调用清空该表；`create_u64_pair_index` 幂等，可放心重复调。
4. `get_row_handle` 缓冲必须**恰好** `row_bytes`（`snapshot_info` 给）；`filter` 的 out_rows 缓冲长度不能为 0。
5. blob id **1-based**、不去重；store 名仅 `[A-Za-z0-9_]`（≤64 字节）；value ≤ 16MB。
6. 无自增列：id 靠 `max_u64 + 1`（空表 max=0）。
7. pair index 同 key1 内天然按 key2 有序——"按 session 查 + 按 seq 排"一次 filter 搞定，不必再 sort。
8. `limit=0` 的 filter/sort 返回 `written=0` 但 `total` 正常，可用于只取总数（但 out_rows 仍需非空缓冲）。
9. 写操作（init/insert/blob_put/create_index）用 root+表名；读操作（filter/sort/get/max/blob_value_*_handle）
   走 `open_read_table` 拿到的 handle；读完 `close_read_table`。
10. `.sla` 里 `VEC_AS_PTR` 等宏的表达式形式有方言坑（见实测记录），指南中的 struct 缓冲方案是已验证可编译运行的写法，
    照抄即可。
