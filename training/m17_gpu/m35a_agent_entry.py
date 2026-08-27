"""Repository-root-friendly entry point for the M35A Arena direct-policy agent."""

from splendor_gpu.m35a_agent import main


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import sys

        sys.stderr.write(f"error: {error}\n")
        sys.stderr.flush()
        raise SystemExit(1)
