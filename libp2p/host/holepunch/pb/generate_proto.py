#!/usr/bin/env python3
import subprocess


def generate_proto() -> None:
    subprocess.run(
        ["protoc", "--python_out=.", "-I.", "holepunch.proto"],
        check=True,
    )


if __name__ == "__main__":
    generate_proto()
