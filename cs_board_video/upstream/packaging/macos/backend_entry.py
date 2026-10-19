from webapp.server import app
import uvicorn


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18765, log_level="info")
