from typing import TypedDict, List, Dict, Any, Optional, Union
import yaml
import os


class IConfigQueue(TypedDict):
    queue_name: str
    tags: List[str]
    schemas: List[Dict[Any, Any]]


class IConfigWorkerGit(TypedDict):
    url: str
    username: Optional[str]
    password: Optional[str]


class IConfigWorker(TypedDict):
    path: str


class IConfig(TypedDict):
    queues: List[IConfigQueue]
    worker: Union[IConfigWorker, IConfigWorkerGit]


class PathDoesntExist(Exception):
    pass


def load_config() -> IConfig:
    """Loads the configuration file and returns it

    :raises PathDoesntExist: Raises if config file doesn't exist
    :return: The configuration
    :rtype: IConfig
    """
    if not (os.path.exists(os.path.join(os.getcwd(), "config.yml")) and not \
        os.path.isdir(os.path.join(os.getcwd(), "config.yml"))):
        raise PathDoesntExist(f"Path {os.path.join(os.getcwd(), 'config.yml')} doesn't exist, or it's not a file.")
    
    with open("config.yml", "r") as f:
        contents = yaml.safe_load(f)
    return contents