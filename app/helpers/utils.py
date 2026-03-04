import datetime
import logging
import logging.config
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def get_logging_cfg() -> Any:
    cfg_file = os.getenv("LOGGING_CFG", "app/config/logging-cfg-local.yaml")
    if "LOGS_DIR" not in os.environ:
        logs_dir = Path(__file__).resolve(strict=True).parent.parent.parent / "logs"
        os.environ["LOGS_DIR"] = str(logs_dir)
    print(f"LOGS_DIR is {os.environ['LOGS_DIR']}")  # noqa: T201
    print(f"LOGGING_CFG is {cfg_file}")  # noqa: T201

    with open(cfg_file, encoding="utf-8") as fd:
        config: Any = yaml.safe_load(os.path.expandvars(fd.read()))

    logger.debug("Load logging configuration from file %s", cfg_file)
    return config


def init_logging() -> None:
    config = get_logging_cfg()
    logging.config.dictConfig(config)


def get_iso_8601_timestamp() -> str:
    """Returns the current UTC time as an ISO 8601 string."""
    now_utc = datetime.datetime.now(datetime.UTC)
    return now_utc.isoformat()


def touch_probe_file(file_path: str) -> None:
    """Create or touch a probe file to signal readiness or liveness."""
    if not file_path:
        return
    try:
        Path(file_path).touch()
        logger.debug("Probe file created/updated: %s", file_path)
    except OSError:
        logger.exception("Error creating probe file: %s", file_path)
