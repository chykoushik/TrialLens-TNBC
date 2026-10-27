import os

import uvicorn


def settings():
    value = os.environ.get("PORT", "8080")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 65535:
        raise ValueError("Invalid public port")
    return {"host": "0.0.0.0", "port": int(value), "workers": 1,
            "limit_concurrency": 16, "timeout_keep_alive": 5, "access_log": False}


def main():
    uvicorn.run("backend.public_demo:app", **settings())


if __name__ == "__main__":
    main()
