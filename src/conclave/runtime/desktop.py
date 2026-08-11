from dataclasses import dataclass
import os

from conclave.cli.config import ConclaveConfig
from conclave.runtime.browser import server_url
from conclave.runtime.paths import RuntimePaths, get_runtime_paths
from conclave.runtime.process import find_free_port


@dataclass(frozen=True)
class LaunchConfig:
    config: ConclaveConfig
    paths: RuntimePaths
    url: str


def prepare_launch_config(
    config: ConclaveConfig,
    host: str | None = None,
    port: int | None = None,
    debug: bool = False,
    open_browser: bool = False,
) -> LaunchConfig:
    paths = get_runtime_paths().ensure()

    config.host = host or config.host
    preferred_port = port or config.port
    if open_browser:
        config.port = find_free_port(config.host, preferred=preferred_port)
    else:
        config.port = preferred_port
    if debug:
        config.debug = True

    if "CONCLAVE_DB_PATH" not in os.environ:
        config.db_path = paths.db_path
    if "CONCLAVE_WORKSPACE" not in os.environ:
        os.environ["CONCLAVE_WORKSPACE"] = str(paths.workspace_dir)

    return LaunchConfig(
        config=config,
        paths=paths,
        url=server_url(config.host, config.port),
    )
