import subprocess

from fastapi import FastAPI

app = FastAPI()


@app.get("/run")
def run(cmd: str = ""):
    return subprocess.check_output(cmd, shell=True)


@app.get("/calc")
def calc(expression: str):
    return eval(expression)


def collect(items=[]):
    items.append(1)
    return items
