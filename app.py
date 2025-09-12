import os
import uuid
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from typing import Optional, Tuple
import shutil, subprocess, json
from pathlib import Path
import logging

app = FastAPI(title="Chain Bridge API")

# --------------------------
# 日志配置
# --------------------------
LOG_DIR = Path("./logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_TEXT_FILE = LOG_DIR / "chain_gateway.log"
LOG_JSONL_FILE = LOG_DIR / "chain_gateway.jsonl"


def init_logger():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_TEXT_FILE, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )


init_logger()


def log_command_result(command: str, success: int, stdout: str, stderr: str):
    """记录命令执行日志"""
    log_record = {
        "timestamp": datetime.now().isoformat(),
        "command": command,
        "success": success,
        "stdout": stdout,
        "stderr": stderr
    }
    # 写入 JSONL 文件
    with LOG_JSONL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_record, ensure_ascii=False) + "\n")
    # 同时写到标准日志
    logging.info(json.dumps(log_record, ensure_ascii=False))


# --------------------------
# 工具函数
# --------------------------
def process_output(output: Optional[str]):
    if not output:
        return []
    output = output.strip()
    if output.startswith("{") or output.startswith("["):
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass
    return output.splitlines()


def run_cmd(cmd_list: list[str], input_text: Optional[str] = None) -> Tuple[int, str, str]:
    """
    执行命令并返回 (exit_code, stdout, stderr)
    input_text: 如果命令需要交互输入，可以传入字符串（例如 'y\n'）
    """
    try:
        proc = subprocess.Popen(
            cmd_list,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = proc.communicate(input=input_text)
        return proc.returncode, stdout.strip(), stderr.strip()
    except Exception as e:
        return 255, "", f"Failed to run command: {e}"


def make_file(prefix="tx"):
    """生成唯一 JSON 文件名"""
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.json"


def save_stdout_to_file(stdout: str, prefix: str) -> str:
    """将 stdout 写入 JSON 文件并返回文件路径"""
    file_path = make_file(prefix)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(stdout)
    return file_path


def log_command(command: list[str]):
    record = {
        "timestamp": datetime.now().isoformat(),
        "command": " ".join(command)
    }
    with LOG_JSONL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------
# 核心接口：命令执行（动态 binary）
# --------------------------
@app.api_route("/{binary}/{command_type}/{full_path:path}", methods=["POST"])
async def execute_command(binary: str, command_type: str, full_path: str, request: Request):
    bin_path: Optional[str] = shutil.which(binary)
    if not bin_path:
        raise HTTPException(status_code=400, detail=f"Binary not found for {binary}")

    subcommands = full_path.strip("/").split("/") if full_path else []
    base_cmd = [bin_path, command_type] + subcommands

    # query 参数
    for _, v in request.query_params.multi_items():
        if v is not None:
            # 如果是对象，也转成字符串
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            base_cmd.append(str(v))

    # form-data 参数
    form = await request.form()
    generate_only_file = None
    for k, v in form.items():
        k_lower = k.lower()
        # 布尔类型
        if k_lower in ("y", "yes") and str(v).lower() in ("true", "1"):
            base_cmd.append(f"-{k_lower}" if k_lower == "y" else f"--{k_lower}")
            continue

        # 对象参数处理
        if isinstance(v, (dict, list)):
            v = json.dumps(v)

        if v:
            base_cmd.append(f"--{k}={v}")

        if k_lower == "generate-only" and str(v).lower() in ("true", "1"):
            generate_only_file = make_file("tx-generate-only")

    # 执行命令
    try:
        exit_code, stdout, stderr = run_cmd(base_cmd, input_text="y\n")
    except Exception as e:
        exit_code, stdout, stderr = 255, "", str(e)

    # 记录日志
    log_command(base_cmd)

    # 多签 sign
    if "sign" in subcommands:
        sign_file = save_stdout_to_file(stdout, "tx-sign")
        return {"command": " ".join(base_cmd), "success": exit_code, "stdout": sign_file,
                "stderr": process_output(stderr)}

    # 多签 merge
    if "multisign" in subcommands:
        multisign_file = save_stdout_to_file(stdout, "tx-multisign")
        return {"command": " ".join(base_cmd), "success": exit_code, "stdout": multisign_file,
                "stderr": process_output(stderr)}

    # 广播
    if "broadcast" in subcommands:
        return {"command": " ".join(base_cmd), "success": exit_code, "stdout": process_output(stdout),
                "stderr": process_output(stderr)}

    # generate-only
    if generate_only_file:
        with open(generate_only_file, "w", encoding="utf-8") as f:
            f.write(stdout)
        return {"command": " ".join(base_cmd), "success": exit_code, "stdout": generate_only_file,
                "stderr": process_output(stderr), "msg": "等待返回，控制台查看结果！"}

    # 普通命令
    cmd_for_display = " ".join(f'"{x}"' if x == "" else x for x in base_cmd)

    return {"command": cmd_for_display, "success": exit_code, "stdout": process_output(stdout),
            "stderr": process_output(stderr)}


# --------------------------
# 查询日志
# --------------------------
@app.get("/logs")
async def get_logs(lines: int = 100, keyword: Optional[str] = None):
    if not LOG_JSONL_FILE.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    with LOG_JSONL_FILE.open("r", encoding="utf-8") as f:
        all_lines = f.readlines()
    raw_tail = all_lines[-lines:] if lines > 0 else all_lines
    records = []
    for ln in raw_tail:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if keyword and keyword.lower() not in json.dumps(rec).lower():
            continue
        records.append(rec)
    return {"lines_requested": lines, "returned": len(records), "records": records}


# --------------------------
# 清空日志
# --------------------------
@app.delete("/logs/clear")
async def clear_logs():
    cleared = []
    errors = []
    for log_file in [LOG_TEXT_FILE, LOG_JSONL_FILE]:
        try:
            if log_file.exists():
                log_file.unlink()
            log_file.write_text("", encoding="utf-8")
            cleared.append(str(log_file))
        except Exception as e:
            errors.append({"file": str(log_file), "error": str(e)})
    init_logger()
    if errors:
        raise HTTPException(status_code=500, detail={"cleared": cleared, "errors": errors})
    return {"status": "ok", "cleared_files": cleared}


# --------------------------
# 清理生成的 JSON 文件
# --------------------------
@app.delete("/json/clear")
async def clear_json_files():
    cleared = []
    errors = []
    # 遍历当前目录及子目录，清理所有 .json 文件
    for root, dirs, files in os.walk("."):
        for f in files:
            if f.endswith(".json"):
                file_path = Path(root) / f
                try:
                    file_path.unlink()
                    cleared.append(str(file_path))
                except Exception as e:
                    errors.append({"file": str(file_path), "error": str(e)})
    if errors:
        raise HTTPException(status_code=500, detail={"cleared": cleared, "errors": errors})
    return {"status": "ok", "cleared_files": cleared}
