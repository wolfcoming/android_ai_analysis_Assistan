"""Android hprof 堆转储解析器 — 提取类直方图（实例数 + 总大小 Top N）"""

import struct
import io
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


def parse_hprof_file(filepath: str) -> dict:
    """
    解析 Android hprof 文件，返回类直方图。
    Android hprof 文件格式与标准 Java hprof 不同：
    - 头部不是 "JAVA PROFILE 1.0.x" 而是 Android 特殊格式
    - 使用 hprof-conv 转换后是标准格式
    本解析器同时支持两种格式（尽力兼容）。
    """
    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 20:
        return {"error": f"文件太小 ({len(data)} bytes)，可能不是有效的 hprof 文件"}

    file_size_mb = len(data) / (1024 * 1024)
    if file_size_mb > 150:
        return {
            "error": (
                f"hprof 文件过大 ({file_size_mb:.0f} MB)，解析耗时过长。"
                "建议在 Android Studio Profiler 中打开此文件进行分析，"
                "或通过命令行 dumpsys meminfo 查看实时内存概况。"
            )
        }

    return _parse_hprof(data)


def _parse_hprof(data: bytes) -> dict:
    buf = io.BytesIO(data)
    file_size = len(data)

    # === 读取头部 ===
    # 格式名（null-terminated）
    format_name = b""
    while True:
        ch = buf.read(1)
        if not ch:
            return {"error": "文件头格式异常：在格式名处读到 EOF"}
        if ch == b"\x00":
            break
        format_name += ch

    # ID 大小（4 或 8 字节）
    id_size_bytes = buf.read(4)
    if len(id_size_bytes) < 4:
        return {"error": "无法读取 ID 大小"}
    id_size = struct.unpack(">I", id_size_bytes)[0]
    if id_size not in (4, 8):
        return {"error": f"不支持的 ID 大小: {id_size}"}

    # 时间戳（8 字节）
    _ts = buf.read(8)

    # === 第一遍：收集 STRING 和 LOAD_CLASS ===
    strings = {}  # string_id → string_value
    class_name_map = {}  # class_object_id → class_name_string_id
    class_serial_to_id = {}  # class_serial → class_object_id

    _scan_records(buf, id_size, strings, class_name_map, class_serial_to_id, scan_only=True)

    # === 第二遍：收集 CLASS_DUMP 和 INSTANCE_DUMP ===
    buf.seek(0)
    _skip_header(buf)
    class_info = {}  # class_id → {"name": str, "instance_size": int}
    histogram = defaultdict(lambda: {"count": 0, "total_size": 0})  # class_name → stats

    _scan_records(buf, id_size, strings, class_name_map, class_serial_to_id,
                  scan_only=False, class_info=class_info,
                  histogram=histogram)

    # === 构建结果 ===
    class_list = []
    for class_name, stats in histogram.items():
        cls = class_info.get(class_name, {})
        class_list.append({
            "class_name": class_name,
            "instance_count": stats["count"],
            "total_size": stats["total_size"],
            "instance_size": cls.get("instance_size", 0),
        })

    class_list.sort(key=lambda x: x["total_size"], reverse=True)
    top50 = class_list[:50]

    total_instances = sum(c["instance_count"] for c in top50)
    total_bytes = sum(c["total_size"] for c in top50)

    return {
        "format": format_name.decode("utf-8", errors="replace"),
        "id_size": id_size,
        "file_size": file_size,
        "total_instances_top50": total_instances,
        "total_bytes_top50": total_bytes,
        "top_classes": top50,
    }


def _skip_header(buf):
    """跳过 hprof 头部"""
    while buf.read(1) != b"\x00":
        pass
    buf.read(4)  # id_size
    buf.read(8)  # timestamp


def _read_id(buf, id_size):
    """读取一个 ID（大端）"""
    b = buf.read(id_size)
    if len(b) < id_size:
        return None
    if id_size == 4:
        return struct.unpack(">I", b)[0]
    else:
        return struct.unpack(">Q", b)[0]


def _scan_records(buf, id_size, strings, class_name_map, class_serial_to_id,
                  scan_only=False, class_info=None, histogram=None,
                  **kwargs):
    """扫描 hprof 记录 — scan_only=True 只收集字符串和类映射"""
    record_count = 0
    MAX_RECORDS = 500000  # 安全上限，防止超大文件卡死
    while True:
        record_count += 1
        if record_count > MAX_RECORDS:
            break

        tag_byte = buf.read(1)
        if not tag_byte:
            break
        tag = tag_byte[0]

        time_data = buf.read(4)
        if len(time_data) < 4:
            break

        length_data = buf.read(4)
        if len(length_data) < 4:
            break
        body_length = struct.unpack(">I", length_data)[0]

        body_bytes = buf.read(body_length)
        if len(body_bytes) < body_length:
            break
        body = io.BytesIO(body_bytes)

        if tag == TAG_STRING:
            string_id = struct.unpack(">I", body.read(4))[0]
            strings[string_id] = body.read().decode("utf-8", errors="replace")

        elif tag == TAG_LOAD_CLASS:
            class_serial = struct.unpack(">I", body.read(4))[0]
            class_obj_id = _read_id(body, id_size)
            body.read(4)  # stack_trace_serial
            class_name_id = struct.unpack(">I", body.read(4))[0]
            if class_obj_id is not None:
                class_name_map[class_obj_id] = class_name_id
            class_serial_to_id[class_serial] = class_obj_id

        elif tag in (TAG_HEAP_DUMP, TAG_HEAP_SEGMENT):
            if scan_only:
                continue
            _parse_heap_dump(body, id_size, strings, class_name_map,
                            class_info, class_serial_to_id, histogram)


def _parse_heap_dump(body, id_size, strings, class_name_map,
                     class_info, class_serial_to_id, histogram):
    """解析 HEAP_DUMP 段的子记录"""
    sub_record_count = 0
    MAX_SUB_RECORDS = 1000000
    while True:
        sub_record_count += 1
        if sub_record_count > MAX_SUB_RECORDS:
            break

        tag_byte = body.read(1)
        if not tag_byte:
            break
        tag = tag_byte[0]

        if tag == HPROF_GC_ROOT_UNKNOWN:
            _read_id(body, id_size)

        elif tag == HPROF_GC_ROOT_JNI_GLOBAL:
            _read_id(body, id_size)
            _read_id(body, id_size)

        elif tag == HPROF_GC_ROOT_JNI_LOCAL:
            _read_id(body, id_size)
            body.read(4)  # thread_serial
            body.read(4)  # frame_number

        elif tag == HPROF_GC_ROOT_JAVA_FRAME:
            _read_id(body, id_size)
            body.read(4)  # thread_serial
            body.read(4)  # frame_number

        elif tag == HPROF_GC_ROOT_NATIVE_STACK:
            _read_id(body, id_size)
            body.read(4)  # thread_serial

        elif tag == HPROF_GC_ROOT_STICKY_CLASS:
            _read_id(body, id_size)

        elif tag == HPROF_GC_ROOT_THREAD_BLOCK:
            _read_id(body, id_size)
            body.read(4)  # thread_serial

        elif tag == HPROF_GC_ROOT_MONITOR_USED:
            _read_id(body, id_size)

        elif tag == HPROF_GC_ROOT_THREAD_OBJ:
            _read_id(body, id_size)
            body.read(4)  # thread_serial
            body.read(4)  # stack_trace_serial

        elif tag == HPROF_GC_CLASS_DUMP:
            class_id = _read_id(body, id_size)
            body.read(4)  # stack_trace_serial
            super_class_id = _read_id(body, id_size)
            class_loader_id = _read_id(body, id_size)
            body.read(4)  # signers_id (id_size)
            body.read(4)  # protection_domain_id (id_size)
            body.read(id_size)  # reserved1
            body.read(id_size)  # reserved2
            instance_size_data = body.read(4)
            if len(instance_size_data) < 4:
                break
            instance_size = struct.unpack(">I", instance_size_data)[0]
            body.read(2)  # constant_pool_size
            # ... skip rest of CLASS_DUMP fields (static fields)
            # Read the number of static fields
            sf_data = body.read(2)
            if len(sf_data) < 2:
                break
            num_static_fields = struct.unpack(">H", sf_data)[0]
            # Skip static fields: each has name_id(id_size) + type(1) + value(variable)
            for _ in range(num_static_fields):
                _read_id(body, id_size)  # name_id
                type_byte = body.read(1)
                if not type_byte:
                    break
                # Skip value based on type
                _skip_value(body, type_byte[0], id_size)
            # Read number of instance fields
            if_data = body.read(2)
            if len(if_data) < 2:
                break
            num_instance_fields = struct.unpack(">H", if_data)[0]
            # Skip instance field descriptors
            for _ in range(num_instance_fields):
                _read_id(body, id_size)  # name_id
                body.read(1)  # type

            # Resolve class name
            name_id = class_name_map.get(class_id)
            class_name = strings.get(name_id, f"<unknown-{class_id}>") if name_id else f"<unknown-{class_id}>"
            if class_info is not None:
                class_info[class_name] = {"instance_size": instance_size}

        elif tag == HPROF_GC_INSTANCE_DUMP:
            obj_id = _read_id(body, id_size)
            body.read(4)  # stack_trace_serial
            class_id = _read_id(body, id_size)
            instance_data_size = struct.unpack(">I", body.read(4))[0]
            body.seek(instance_data_size, 1)  # skip instance data

            # Resolve class name and update histogram
            name_id = class_name_map.get(class_id)
            class_name = strings.get(name_id, f"<unknown-{class_id}>") if name_id else f"<unknown-{class_id}>"
            cls = class_info.get(class_name, {}) if class_info else {}
            inst_size = cls.get("instance_size", instance_data_size)
            if histogram is not None:
                histogram[class_name]["count"] += 1
                histogram[class_name]["total_size"] += inst_size

        elif tag == HPROF_GC_OBJ_ARRAY_DUMP:
            array_id = _read_id(body, id_size)
            body.read(4)  # stack_trace_serial
            num_elements = struct.unpack(">I", body.read(4))[0]
            array_class_id = _read_id(body, id_size)
            # element IDs
            for _ in range(num_elements):
                _read_id(body, id_size)
            # Count in histogram
            name_id = class_name_map.get(array_class_id)
            class_name = strings.get(name_id, f"<array-{array_class_id}>") if name_id else f"<array-{array_class_id}>"
            if histogram is not None:
                histogram[class_name]["count"] += 1
                histogram[class_name]["total_size"] += num_elements * id_size

        elif tag == HPROF_GC_PRIM_ARRAY_DUMP:
            array_id = _read_id(body, id_size)
            body.read(4)  # stack_trace_serial
            num_elements = struct.unpack(">I", body.read(4))[0]
            elem_type = body.read(1)
            if not elem_type:
                break
            elem_size = PRIM_SIZES.get(elem_type[0], 4)
            body.seek(num_elements * elem_size, 1)
            # Count in histogram
            type_names = {2: "boolean[]", 4: "char[]", 5: "short[]", 7: "long[]",
                         8: "float[]", 9: "int[]", 10: "double[]", 11: "byte[]"}
            class_name = type_names.get(elem_type[0], f"primitive[{elem_type[0]}]")
            if histogram is not None:
                histogram[class_name]["count"] += 1
                histogram[class_name]["total_size"] += num_elements * elem_size

        elif tag == HPROF_GC_HEAP_DUMP_INFO:
            body.read(4)  # heap_type
            _read_id(body, id_size)  # heap_name_id

        elif tag == HPROF_GC_ROOT_UNREACHABLE:
            _read_id(body, id_size)

        else:
            # Unknown tag — try to skip gracefully
            break


def _skip_value(body, type_byte, id_size):
    """跳过静态字段值"""
    if type_byte == 2:  # object
        _read_id(body, id_size)
    elif type_byte in (1, 3, 4, 5, 6):  # byte, boolean, short, char, int, float
        body.read(4)
    elif type_byte in (7, 8):  # long, double
        body.read(8)
