import time, uuid, json, shutil, subprocess, logging, os, tempfile
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Header, HTTPException

app = FastAPI(title="Chain Bridge")

# --------------------------
# 可执行文件默认探测
# --------------------------
BINARY_MAP = {
    "gead": shutil.which("gead"),
    "gc": shutil.which("gcd"),
    "me": shutil.which("med"),
}

# --------------------------
# 日志文件
# --------------------------
LOG_TEXT_FILE = Path("chain_gateway.log")
LOG_JSONL_FILE = Path("chain_gateway.log.jsonl")

# --------------------------
# 日志初始化与管理
# --------------------------
def init_logger():
    global logger
    if 'logger' in globals():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
    logging.basicConfig(
        filename=str(LOG_TEXT_FILE),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger(__name__)

def ensure_log_files():
    for log_file in [LOG_TEXT_FILE, LOG_JSONL_FILE]:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if not log_file.exists():
            log_file.write_text("", encoding="utf-8")

ensure_log_files()
init_logger()

def append_jsonl(record: dict):
    ensure_log_files()
    with LOG_JSONL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass

# --------------------------
# 工具函数
# --------------------------
def process_output(output: Optional[str]):
    if not output:
        return None
    output = output.strip()
    if output.startswith("{") or output.startswith("["):
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass
    return output.splitlines()

def run_cmd(cmd_list: list) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd_list, capture_output=True, text=True, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 255, "", f"Failed to run command: {e}"

# --------------------------
# 核心接口：命令执行
# --------------------------
@app.api_route("/{binary}/{command_type}/{full_path:path}", methods=["POST"])
async def execute_command(
        binary: str,
        command_type: str,
        full_path: str,
        request: Request,
        x_env_use_multisig: str = Header(default="false"),
        x_use_multisig: str = Header(default="false"),
        x_multisig_signers: str = Header(default=""),
        x_multisig_name: str = Header(default="")):

    bin_path: Optional[str] = BINARY_MAP.get(binary) or shutil.which(binary)
    if not bin_path:
        raise HTTPException(status_code=400, detail=f"Binary not found for {binary}")

    subcommands = full_path.strip("/").split("/") if full_path else []
    base_cmd = [bin_path, command_type] + subcommands

    env_multisig = x_env_use_multisig.lower() == "true"
    cmd_multisig = x_use_multisig.lower() == "true"
    use_multisig = env_multisig and cmd_multisig

    multisig_signers = [s.strip() for s in x_multisig_signers.split(",") if s.strip()]
    multisig_name = x_multisig_name.strip()

    query_items = list(request.query_params.multi_items())
    for _, v in query_items:
        if v is not None:
            base_cmd.append(v)

    form = await request.form()
    chain_id = node = home = keyring_backend = multisig_addr = None
    for k, v in form.items():
        k_lower = k.lower()
        if k_lower in ("y", "yes"):
            base_cmd.append(f"-{k_lower}" if k_lower == "y" else f"--{k_lower}")
            continue
        if v:
            base_cmd.append(f"--{k}={v}")
        if k == "chain-id": chain_id = v
        if k == "node": node = v
        if k == "home": home = v
        if k == "keyring-backend": keyring_backend = v
        if k == "from": multisig_addr = v

    result = {}
    steps = {}
    file_prefix = f"tx-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    temp_files = []

    temp_dir = Path(tempfile.gettempdir()) / "chain_gateway_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        if not use_multisig:
            exit_code, stdout_raw, stderr_raw = run_cmd(base_cmd)
            success = exit_code == 0
            steps["execute"] = {
                "command": " ".join(base_cmd),
                "success": success,
                "stdout": process_output(stdout_raw),
                "stderr": process_output(stderr_raw)
            }
            result = steps["execute"]
        else:
            # Step 1: 生成交易
            unsigned_file = temp_dir / f"{file_prefix}-unsigned.json"
            exit_code, stdout_raw, stderr_raw = run_cmd(base_cmd + ["--generate-only"])
            success = exit_code == 0
            steps["generate"] = {
                "command": " ".join(base_cmd + ["--generate-only"]),
                "success": success,
                "stdout": process_output(stdout_raw),
                "stderr": process_output(stderr_raw)
            }
            if not success:
                result = steps["generate"]
                return result
            with open(unsigned_file, "w", encoding="utf-8") as f: f.write(stdout_raw)
            temp_files.append(unsigned_file)

            # Step 2: 多签签名
            signed_files = []
            steps["sign"] = {}
            for signer in multisig_signers:
                signed_file = temp_dir / f"{file_prefix}-signed-{signer}.json"
                cmd_sign = [
                    bin_path, "tx", "sign", str(unsigned_file),
                    "--from", signer,
                    "--multisig", multisig_addr,
                    "--chain-id", chain_id,
                    "--node", node,
                    "--home", home,
                    "--keyring-backend", keyring_backend,
                    "-o", "json"]
                exit_code, stdout_raw, stderr_raw = run_cmd(cmd_sign)
                success = exit_code == 0
                steps["sign"][signer] = {
                    "command": " ".join(cmd_sign),
                    "success": success,
                    "stdout": process_output(stdout_raw),
                    "stderr": process_output(stderr_raw)
                }
                if not success:
                    result = steps
                    return result
                with open(signed_file, "w", encoding="utf-8") as f: f.write(stdout_raw)
                signed_files.append(signed_file)
                temp_files.append(signed_file)

            # Step 3: 合并签名
            multisigned_file = temp_dir / f"{file_prefix}-multisigned.json"
            cmd_multisign = [bin_path, "tx", "multisign", str(unsigned_file), multisig_name] + [str(f) for f in signed_files] + [
                "--chain-id", chain_id,
                "--node", node,
                "--home", home,
                "--keyring-backend", keyring_backend,
                "-o", "json"]
            exit_code, stdout_raw, stderr_raw = run_cmd(cmd_multisign)
            success = exit_code == 0
            steps["multisign"] = {
                "command": " ".join(cmd_multisign),
                "success": success,
                "stdout": process_output(stdout_raw),
                "stderr": process_output(stderr_raw)
            }
            if not success:
                result = steps
                return result
            with open(multisigned_file, "w", encoding="utf-8") as f: f.write(stdout_raw)
            temp_files.append(multisigned_file)

            # Step 4: 广播
            cmd_broadcast = [bin_path, "tx", "broadcast", str(multisigned_file),
                             "--chain-id", chain_id,
                             "--node", node,
                             "--home", home,
                             "--keyring-backend", keyring_backend,
                             "-o", "json"]
            exit_code, stdout_raw, stderr_raw = run_cmd(cmd_broadcast)
            success = exit_code == 0
            steps["broadcast"] = {
                "command": " ".join(cmd_broadcast),
                "success": success,
                "stdout": process_output(stdout_raw),
                "stderr": process_output(stderr_raw)
            }
            result = steps["broadcast"]

    finally:
        for f in temp_files:
            try: f.unlink()
            except Exception: pass

    # 统一写一条日志，包含所有步骤
    log_record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "url": str(request.url),
        "multisig": use_multisig,
        "steps": steps,
        "final_result": result
    }
    append_jsonl(log_record)
    logger.info(f"Command executed, final result: {result}")

    return result

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
        if not ln: continue
        try: rec = json.loads(ln)
        except json.JSONDecodeError: continue
        if keyword and keyword.lower() not in json.dumps(rec).lower(): continue
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
            if log_file.exists(): log_file.unlink()
            log_file.write_text("", encoding="utf-8")
            cleared.append(str(log_file))
        except Exception as e:
            errors.append({"file": str(log_file), "error": str(e)})
    init_logger()
    if errors:
        raise HTTPException(status_code=500, detail={"cleared": cleared, "errors": errors})
    return {"status": "ok", "cleared_files": cleared}
