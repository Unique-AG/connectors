#!/usr/bin/env python3
"""Generate Python gRPC code from proto files."""

import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).parent
    proto_file = project_root / "proto" / "sparse_embedding.proto"

    if not proto_file.exists():
        print(f"Error: Proto file not found at {proto_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Generating Python gRPC code from {proto_file.name}...")

    try:
        from grpc_tools import protoc  # pyright: ignore[reportMissingTypeStubs]

        result = protoc.main([  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            "grpc_tools.protoc",
            f"-I{project_root}",
            f"--python_out={project_root}",
            f"--grpc_python_out={project_root}",
            f"--pyi_out={project_root}",
            "proto/sparse_embedding.proto",
        ])

        if result == 0:
            print("✓ Generated Python gRPC code in proto/")
            print("  - proto/sparse_embedding_pb2.py")
            print("  - proto/sparse_embedding_pb2.pyi")
            print("  - proto/sparse_embedding_pb2_grpc.py")
        else:
            print("Error generating proto files", file=sys.stderr)
            sys.exit(result)  # pyright: ignore[reportUnknownArgumentType]

    except ImportError:
        print("Error: grpcio-tools not installed", file=sys.stderr)
        print("Run: uv sync", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

