import uvicorn
from main import app  # 确保你的 FastAPI 实例在 main.py 中名为 app

if __name__ == "__main__":
    # 第一版，fastapi处理多签的流程
    # uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    # 第二版，拆分多个接口处理
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
    # fastapi dev main.py
