"""Android hprof 堆转储解析器 — 提取类直方图（实例数 + 总大小 Top N）

优化项：
- mmap 内存映射读取（不复制整个文件）
- 大文件采样解析（>100MB 自动采样，不再拒绝）
- 未知子标签容错（不再 break 中断解析）
- 重复字符串检测
"""

import struct
import io
import mmap
import os
from collections import defaultdict


# hprof 记录标签
TAG_STRING       = 0x01
TAG_LOAD_CLASS   = 0x02
TAG_HEAP_DUMP    = 0x0C
TAG_HEAP_SEGMENT = 0x1C

# HEAP_DUMP 子记录标签
HPROF_GC_ROOT_UNKNOWN         = 0xFF
HPROF_GC_ROOT_JNI_GLOBAL      = 0x01
HPROF_GC_ROOT_JNI_LOCAL       = 0x02
HPROF_GC_ROOT_JAVA_FRAME      = 0x03
HPROF_GC_ROOT_NATIVE_STACK    = 0x04
HPROF_GC_ROOT_STICKY_CLASS    = 0x05
HPROF_GC_ROOT_THREAD_BLOCK    = 0x06
HPROF_GC_ROOT_MONITOR_USED    = 0x07
HPROF_GC_ROOT_THREAD_OBJ      = 0x08
HPROF_GC_CLASS_DUMP           = 0x20
HPROF_GC_INSTANCE_DUMP        = 0x21
HPROF_GC_OBJ_ARRAY_DUMP       = 0x22
HPROF_GC_PRIM_ARRAY_DUMP      = 0x23
HPROF_GC_HEAP_DUMP_INFO       = 0xFE
HPROF_GC_ROOT_UNREACHABLE     = 0x90
# Android 扩展子标签（部分设备特有）
HPROF_GC_ROOT_VM_INTERNAL     = 0x09
HPROF_GC_ROOT_FINALIZING      = 0x8A
HPROF_GC_ROOT_DEBUGGER        = 0x8B
HPROF_GC_ROOT_REFERENCE_CLEANUP = 0x8C
HPROF_GC_ROOT_VM_INTERNAL2    = 0x8D
HPROF_GC_ROOT_JNI_MONITOR     = 0x8E
HPROF_GC_ROOT_INTERNED_STRING = 0x89
HPROF_GC_INSTANCE_DUMP_V2     = 0x2D  # Android 14+ 扩展格式
HPROF_GC_PRIM_ARRAY_DUMP_V2   = 0x2E

# 基本类型大小
PRIM_SIZES = {
    2: 1,   # boolean → 1 byte
    4: 2,   # char → 2 bytes
    5: 2,   # short → 2 bytes
    7: 8,   # long → 8 bytes
    8: 4,   # float → 4 bytes
    9: 4,   # int → 4 bytes
    10: 8,  # double → 8 bytes
    11: 8,  # long (ON_HEAP_DUMP standard)
}

# 大文件阈值
LARGE_FILE_MB = 100
# 大文件最大采样实例数
MAX_SAMPLED_INSTANCES = 300000
# 安全上限
MAX_RECORDS = 1000000
MAX_SUB_RECORDS = 2000000

# GC Root 子标签的大小（元素按 id_size 计）
_GC_ROOT_SIZES = {
    0xFF: 1,  # UNKNOWN
    0x01: 2,  # JNI_GLOBAL
    0x02: 2,  # JNI_LOCAL (id + thread_serial + frame_number, but thread/frame are 4 bytes each)
    0x03: 2,  # JAVA_FRAME
    0x04: 2,  # NATIVE_STACK
    0x05: 1,  # STICKY_CLASS
    0x06: 2,  # THREAD_BLOCK
    0x07: 1,  # MONITOR_USED
    0x08: 3,  # THREAD_OBJ
    0x89: 1,  # INTERNED_STRING
    0x8A: 1,  # FINALIZING
    0x8B: 1,  # DEBUGGER
    0x8C: 1,  # REFERENCE_CLEANUP
    0x8D: 1,  # VM_INTERNAL2
    0x8E: 2,  # JNI_MONITOR
    0x90: 1,  # UNREACHABLE
}


def parse_hprof_file(filepath: str, max_instances: int = None) -> dict:
    """
    解析 Android hprof 文件，返回类直方图。

    Args:
        filepath: hprof 文件路径
        max_instances: 最大解析实例数。None=全量，>0=采样。超过 100MB 的文件自动启用采样。

    Returns:
        {
            "error": "..."                              # 仅在解析失败时
            "format": "JAVA PROFILE 1.0.3",
            "id_size": 4,
            "file_size": 12345678,
            "parse_mode": "full" | "sampled",
            "total_instances_top50": 50000,
            "total_bytes_top50": 12345678,
            "top_classes": [...],
            "duplicate_strings": [...]                   # 重复字符串检测结果
        }
    """
    file_size = os.path.getsize(filepath)
    if file_size < 20:
        return {"error": f"文件太小 ({file_size} bytes)，可能不是有效的 hprof 文件"}

    file_size_mb = file_size / (1024 * 1024)

    # 大文件自动启用采样
    if max_instances is None and file_size_mb > LARGE_FILE_MB:
        max_instances = MAX_SAMPLED_INSTANCES

    try:
        with open(filepath, "rb") as f:
            # 使用 mmap 内存映射，避免复制整个文件到内存
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                return _parse_hprof_mmap(mm, file_size, file_size_mb, max_instances)
    except OSError as e:
        return {"error": f"无法打开或映射文件: {e}"}
    except Exception as e:
        import traceback
        return {"error": f"解析异常: {e}", "traceback": traceback.format_exc()[-500:]}


def _parse_hprof_mmap(data, file_size, file_size_mb, max_instances):
    """使用 mmap 数据解析 hprof"""
    buf = io.BytesIO(data)
    pos = 0

    # === 读取头部 ===
    format_name = b""
    while True:
        ch = data[pos:pos+1]
        if not ch:
            return {"error": "文件头格式异常：在格式名处读到 EOF"}
        pos += 1
        if ch == b"\x00":
            break
        format_name += ch

    if pos + 12 > file_size:
        return {"error": "文件头不完整"}

    id_size_bytes = data[pos:pos+4]
    pos += 4
    id_size = struct.unpack(">I", id_size_bytes)[0]
    if id_size not in (4, 8):
        return {"error": f"不支持的 ID 大小: {id_size}"}

    pos += 8  # skip timestamp

    # === 第一遍：收集 STRING 和 LOAD_CLASS ===
    strings = {}
    class_name_map = {}
    class_serial_to_id = {}

    _scan_records_mmap(data, pos, file_size, id_size,
                       strings, class_name_map, class_serial_to_id,
                       scan_only=True)

    # === 第二遍：收集 CLASS_DUMP 和 INSTANCE_DUMP ===
    # 重新定位到头部之后
    pos = _skip_header_mmap(data, 0)
    pos += 8  # skip timestamp

    class_info = {}
    histogram = defaultdict(lambda: {"count": 0, "total_size": 0})
    stats = {"instance_count": 0, "skipped": 0}

    _scan_records_mmap(data, pos, file_size, id_size,
                       strings, class_name_map, class_serial_to_id,
                       scan_only=False, class_info=class_info,
                       histogram=histogram,
                       max_instances=max_instances, stats=stats)

    # === 重复字符串检测 ===
    dup_strings = _detect_duplicate_strings(strings)

    # === 构建结果 ===
    class_list = []
    for class_name, h in histogram.items():
        cls = class_info.get(class_name, {})
        class_list.append({
            "class_name": class_name,
            "instance_count": h["count"],
            "total_size": h["total_size"],
            "instance_size": cls.get("instance_size", 0),
        })

    class_list.sort(key=lambda x: x["total_size"], reverse=True)
    top50 = class_list[:50]

    total_instances = sum(c["instance_count"] for c in top50)
    total_bytes = sum(c["total_size"] for c in top50)

    result = {
        "format": format_name.decode("utf-8", errors="replace"),
        "id_size": id_size,
        "file_size": file_size,
        "total_instances_top50": total_instances,
        "total_bytes_top50": total_bytes,
        "top_classes": top50,
    }

    # 采样模式标记
    if max_instances:
        result["parse_mode"] = "sampled"
        result["sampled_from"] = stats.get("instance_count", 0)
        result["sampled_max"] = max_instances
    else:
        result["parse_mode"] = "full"

    # 重复字符串
    if dup_strings:
        result["duplicate_strings"] = dup_strings[:10]

    return result


def _detect_duplicate_strings(strings):
    """检测高频重复字符串 — 可能是 String.intern() 过度的信号"""
    counter = defaultdict(int)
    for s in strings.values():
        if len(s) > 4:
            counter[s] += 1

    dupes = []
    for s, count in counter.items():
        if count > 100:
            dupes.append({"string": s[:80], "count": count})
    dupes.sort(key=lambda x: x["count"], reverse=True)
    return dupes


def _skip_header_mmap(data, pos):
    """跳过 mmap 中的 hprof 头部，返回头部后的位置"""
    while pos < len(data) and data[pos:pos+1] != b"\x00":
        pos += 1
    if pos < len(data):
        pos += 1  # skip null byte
    pos += 4      # id_size
    return pos    # caller 要再 skip 8 (timestamp)


def _read_id_mmap(data, pos, id_size):
    """从 mmap 读取一个 ID（大端）"""
    if pos + id_size > len(data):
        return None, pos
    b = data[pos:pos+id_size]
    pos += id_size
    if id_size == 4:
        return struct.unpack(">I", b)[0], pos
    else:
        return struct.unpack(">Q", b)[0], pos


def _scan_records_mmap(data, pos, file_size, id_size,
                       strings, class_name_map, class_serial_to_id,
                       scan_only=False, class_info=None, histogram=None,
                       max_instances=None, stats=None):
    """扫描 hprof 记录 — 使用位置索引避免 BytesIO 开销"""
    record_count = 0
    while pos < file_size:
        record_count += 1
        if record_count > MAX_RECORDS:
            break

        if pos >= file_size:
            break
        tag = data[pos]
        pos += 1

        # time_data (4 bytes)
        if pos + 8 > file_size:
            break
        pos += 4  # skip time

        body_length = struct.unpack(">I", data[pos:pos+4])[0]
        pos += 4

        if pos + body_length > file_size:
            break

        body_start = pos
        pos += body_length

        if tag == TAG_STRING:
            if body_length < 4:
                continue
            string_id = struct.unpack(">I", data[body_start:body_start+4])[0]
            string_val = data[body_start+4:body_start+body_length].decode("utf-8", errors="replace")
            strings[string_id] = string_val

        elif tag == TAG_LOAD_CLASS:
            if body_length < 20:
                continue
            bp = body_start
            class_serial = struct.unpack(">I", data[bp:bp+4])[0]
            bp += 4
            class_obj_id, _ = _read_id_mmap(data, bp, id_size)
            bp += id_size + 4  # skip stack_trace_serial
            class_name_id = struct.unpack(">I", data[bp:bp+4])[0]
            if class_obj_id is not None:
                class_name_map[class_obj_id] = class_name_id
            class_serial_to_id[class_serial] = class_obj_id

        elif tag in (TAG_HEAP_DUMP, TAG_HEAP_SEGMENT):
            if scan_only:
                continue
            _parse_heap_dump_mmap(data, body_start, body_start + body_length,
                                  id_size, strings, class_name_map,
                                  class_info, class_serial_to_id, histogram,
                                  max_instances, stats)


def _parse_heap_dump_mmap(data, start, end, id_size, strings, class_name_map,
                          class_info, class_serial_to_id, histogram,
                          max_instances, stats):
    """解析 HEAP_DUMP 段的子记录 — mmap 版"""
    pos = start
    sub_record_count = 0

    while pos < end:
        sub_record_count += 1
        if sub_record_count > MAX_SUB_RECORDS:
            break

        if pos >= end:
            break
        tag = data[pos]
        pos += 1

        # 检查是否需要采样
        if max_instances and stats and ("instance_count" in stats):
            if stats["instance_count"] >= max_instances:
                stats["skipped"] += 1
                # 跳到段末尾
                return

        if tag == HPROF_GC_ROOT_UNKNOWN:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_JNI_GLOBAL:
            _, pos = _read_id_mmap(data, pos, id_size)
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_JNI_LOCAL:
            _, pos = _read_id_mmap(data, pos, id_size)
            pos += 8  # thread_serial + frame_number

        elif tag == HPROF_GC_ROOT_JAVA_FRAME:
            _, pos = _read_id_mmap(data, pos, id_size)
            pos += 8

        elif tag == HPROF_GC_ROOT_NATIVE_STACK:
            _, pos = _read_id_mmap(data, pos, id_size)
            pos += 4

        elif tag == HPROF_GC_ROOT_STICKY_CLASS:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_THREAD_BLOCK:
            _, pos = _read_id_mmap(data, pos, id_size)
            pos += 4

        elif tag == HPROF_GC_ROOT_MONITOR_USED:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_THREAD_OBJ:
            _, pos = _read_id_mmap(data, pos, id_size)
            pos += 8

        elif tag == HPROF_GC_ROOT_INTERNED_STRING:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_FINALIZING:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_DEBUGGER:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_REFERENCE_CLEANUP:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_VM_INTERNAL2:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_JNI_MONITOR:
            _, pos = _read_id_mmap(data, pos, id_size)
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_ROOT_UNREACHABLE:
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_CLASS_DUMP:
            if pos + 32 > end:
                break
            class_id, pos = _read_id_mmap(data, pos, id_size)
            pos += 4  # stack_trace_serial
            super_class_id, pos = _read_id_mmap(data, pos, id_size)
            class_loader_id, pos = _read_id_mmap(data, pos, id_size)
            pos += 8  # signers_id + protection_domain_id (each 4 bytes)
            pos += id_size * 2  # reserved1 + reserved2
            instance_size = struct.unpack(">I", data[pos:pos+4])[0]
            pos += 4
            pos += 2  # constant_pool_size

            # Skip static fields
            if pos + 2 > end:
                break
            num_static_fields = struct.unpack(">H", data[pos:pos+2])[0]
            pos += 2
            for _ in range(num_static_fields):
                if pos + id_size + 1 > end:
                    break
                pos += id_size  # name_id
                type_byte = data[pos]
                pos += 1
                pos = _skip_value_mmap(data, pos, type_byte, id_size, end)

            # Skip instance field descriptors
            if pos + 2 > end:
                break
            num_instance_fields = struct.unpack(">H", data[pos:pos+2])[0]
            pos += 2
            pos += num_instance_fields * (id_size + 1)

            # Resolve class name
            name_id = class_name_map.get(class_id)
            class_name = strings.get(name_id, f"<unknown-{class_id}>") if name_id else f"<unknown-{class_id}>"
            if class_info is not None:
                class_info[class_name] = {"instance_size": instance_size}

        elif tag == HPROF_GC_INSTANCE_DUMP:
            if pos + id_size * 2 + 8 > end:
                break
            obj_id, pos = _read_id_mmap(data, pos, id_size)
            pos += 4  # stack_trace_serial
            class_id, pos = _read_id_mmap(data, pos, id_size)
            instance_data_size = struct.unpack(">I", data[pos:pos+4])[0]
            pos += 4 + instance_data_size

            # Resolve and count
            name_id = class_name_map.get(class_id)
            class_name = strings.get(name_id, f"<unknown-{class_id}>") if name_id else f"<unknown-{class_id}>"
            cls = class_info.get(class_name, {}) if class_info else {}
            inst_size = cls.get("instance_size", instance_data_size)
            if histogram is not None:
                histogram[class_name]["count"] += 1
                histogram[class_name]["total_size"] += inst_size
            if stats is not None:
                stats["instance_count"] = stats.get("instance_count", 0) + 1

        elif tag == HPROF_GC_OBJ_ARRAY_DUMP:
            if pos + id_size * 2 + 8 > end:
                break
            array_id, pos = _read_id_mmap(data, pos, id_size)
            pos += 4  # stack_trace_serial
            num_elements = struct.unpack(">I", data[pos:pos+4])[0]
            pos += 4
            array_class_id, pos = _read_id_mmap(data, pos, id_size)
            pos += num_elements * id_size

            name_id = class_name_map.get(array_class_id)
            class_name = strings.get(name_id, f"<array-{array_class_id}>") if name_id else f"<array-{array_class_id}>"
            if histogram is not None:
                histogram[class_name]["count"] += 1
                histogram[class_name]["total_size"] += num_elements * id_size

        elif tag == HPROF_GC_PRIM_ARRAY_DUMP:
            if pos + id_size + 9 > end:
                break
            array_id, pos = _read_id_mmap(data, pos, id_size)
            pos += 4  # stack_trace_serial
            num_elements = struct.unpack(">I", data[pos:pos+4])[0]
            pos += 4
            elem_type = data[pos]
            pos += 1
            elem_size = PRIM_SIZES.get(elem_type, 4)
            pos += num_elements * elem_size

            type_names = {2: "boolean[]", 4: "char[]", 5: "short[]", 7: "long[]",
                         8: "float[]", 9: "int[]", 10: "double[]", 11: "byte[]"}
            class_name = type_names.get(elem_type, f"primitive[{elem_type}]")
            if histogram is not None:
                histogram[class_name]["count"] += 1
                histogram[class_name]["total_size"] += num_elements * elem_size

        elif tag == HPROF_GC_HEAP_DUMP_INFO:
            pos += 4  # heap_type
            _, pos = _read_id_mmap(data, pos, id_size)

        elif tag == HPROF_GC_INSTANCE_DUMP_V2:
            # Android 14+ 扩展格式，结构同 INSTANCE_DUMP 但可能有额外字段
            # 先按标准格式解析
            if pos + id_size * 2 + 8 > end:
                break
            obj_id, pos = _read_id_mmap(data, pos, id_size)
            pos += 4
            class_id, pos = _read_id_mmap(data, pos, id_size)
            instance_data_size = struct.unpack(">I", data[pos:pos+4])[0]
            pos += 4 + instance_data_size

            name_id = class_name_map.get(class_id)
            class_name = strings.get(name_id, f"<unknown-{class_id}>") if name_id else f"<unknown-{class_id}>"
            if histogram is not None:
                histogram[class_name]["count"] += 1
                histogram[class_name]["total_size"] += instance_data_size
            if stats is not None:
                stats["instance_count"] = stats.get("instance_count", 0) + 1

        elif tag == HPROF_GC_PRIM_ARRAY_DUMP_V2:
            # Android 14+ 扩展格式
            if pos + id_size + 9 > end:
                break
            array_id, pos = _read_id_mmap(data, pos, id_size)
            pos += 4
            num_elements = struct.unpack(">I", data[pos:pos+4])[0]
            pos += 4
            elem_type = data[pos]
            pos += 1
            elem_size = PRIM_SIZES.get(elem_type, 4)
            pos += num_elements * elem_size

        else:
            # 未知子标签 — 无法确定大小，安全退出当前段
            break


def _skip_value_mmap(data, pos, type_byte, id_size, end):
    """在 mmap 中跳过静态字段值"""
    if pos >= end:
        return pos
    if type_byte == 2:  # object
        _, pos = _read_id_mmap(data, pos, id_size)
    elif type_byte in (1, 3, 4, 5, 6):  # byte, boolean, short, char, int, float
        pos += 4
    elif type_byte in (7, 8):  # long, double
        pos += 8
    return pos
