import uvicorn
from main import app  # 确保你的 FastAPI 实例在 main.py 中名为 app

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
