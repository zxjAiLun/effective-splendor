"""可直接交给 Arena 启动的 Python 随机 Agent。"""

import argparse
import random

from splendor_env import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    run_agent(lambda decision: rng.choice(decision.legal_actions), name="python-random")


if __name__ == "__main__":
    main()
