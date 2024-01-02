import importlib
import asyncio
import logging
import shutil
import os
import pip
from git.repo import Repo
from fatcat_utils import FatCat
from fatcat_utils.plugin import FatCatPlugin
from fatcat_utils.rabbitmq import RABBIT_CONFIG
from .config import load_config, IConfig


RABBIT_CONFIG["failed_queue"] = os.getenv("FATCAT_RABBIT_WORKER_FAILED_QUEUE", "worker-failed")

class Worker(FatCatPlugin):
    """Worker class.

    Nothing much to document really. Just a class with all the worker functions
    """
    config: IConfig = load_config()
    fatcat: FatCat

    def __init__(self, fatcat: FatCat):
        self.fatcat = fatcat
    
    @FatCat.create_plugin_listener(on="ready")
    async def on_ready(self):
        self.fatcat.logger.info("Inserting queues and schemas to the database")
        await self.insert_queues_to_database()
        self.fatcat.logger.info("Finished inserting queues and schemas to the database")

        if "url" in self.config["worker"]:
            self.fatcat.logger.info("Cloning the worker from Git")
            self.clone_worker()
            self.fatcat.logger.info("Done with the cloning")
        elif "path" in self.config["worker"]:
            self.fatcat.logger.debug("Checking if worker exists")
            if not (os.path.exists(self.config["worker"]["path"]) and os.path.isdir(self.config["worker"]["path"])):
                self.fatcat.logger.error(f"Worker path {self.config['worker']['path']} doesn't exist")
            self.fatcat.logger.debug("Worker path exists")
        else:
            self.fatcat.logger.error("Key error in worker configuration")

        self.fatcat.logger.info("Installing worker dependencies")
        self.install_worker_deps()
        self.fatcat.logger.info("Done installing worker dependencies")

        self.fatcat.logger.info("Loading the worker")
        await self.load_worker()
        self.fatcat.logger.info("Done loading the worker")

    async def insert_queues_to_database(self):
        """Inserts the queues from the configuration to the database
        """
        for queue in self.config["queues"]:
            self.fatcat.logger.debug("Checking if queue document exists")
            queue_doc = await self.fatcat.mongo.get_queue_based_on_name(queue["queue_name"])

            if queue_doc is None or queue_doc == {}:
                self.fatcat.logger.debug("Queue document doesn't exist. Creating new queue and schemas")
                await self.fatcat.mongo.create_queue({
                    "queue_name": queue["queue_name"],
                    "tags": queue["tags"]
                }, queue["schemas"] if "schemas" in queue else None)
            else:
                self.fatcat.logger.debug("Queue document exists. Updating it")
                await self.fatcat.mongo.update_queue({
                    "queue_name": queue["queue_name"], "tags": queue["tags"]
                })
                self.fatcat.logger.debug("Updating schemas in the database")
                await self.fatcat.mongo.update_schema(queue["schemas"] if "schemas" in queue else None, queue["queue_name"])

    async def load_worker(self):
        """Loads the worker from the folder
        """
        self.fatcat.logger.debug("Loading the worker")
        worker = importlib.import_module("worker", os.getcwd())

        load_worker = getattr(worker, "setup_worker")
        if asyncio.coroutines.iscoroutinefunction(worker):
            self.fatcat.logger.debug("Worker's setup function is a coroutine. Awaiting it")
            await load_worker()
        else:
            self.fatcat.logger.debug("Worker's setup function is a normal function (probably). Calling it")
            load_worker()
    
    def install_worker_deps(self):
        """Installing the worker dependencies (if exists)
        """
        if os.path.exists(os.path.join(os.getcwd(), "worker", "requirements.txt")) and not os.path.isdir(os.path.join(os.getcwd(), "worker", "requirements.txt")):
            self.fatcat.logger.debug("Installing worker dependencies")
            if hasattr(pip, "main"):
                pip.main(["install", "-r", os.path.join(os.getcwd(), "worker", "requirements.txt")])
            else:
                pip._internal.main(["install", "-r", os.path.join(os.getcwd(), "worker", "requirements.txt")])
        
        # Pip adds handlers to the root and it's annoying
        for handler in logging.root.handlers:
            logging.root.removeHandler(handler)

    def clone_worker(self):
        """Clones the worker from the git repo according to the configuration
        """
        self.fatcat.logger.debug("Checking if the worker path exists")
        worker_path = os.path.join(os.getcwd(), "worker")
        if not os.path.exists(worker_path):
            self.fatcat.logger.debug("Worker path doesn't exist. Creating it")
            os.mkdir(worker_path)
        elif os.getenv("FATCAT_FORCE_GIT", "1") == "0": 
            self.fatcat.logger.debug("Worker path exists and I was asked not to clean. Exiting function")
            #  Continuing if it exists (this way you can just use it without git)
            return 
        else:
            self.fatcat.logger.debug("Worker path exists. Deleting it and recreating it")
            shutil.rmtree(worker_path)
            os.mkdir(worker_path)

        url = self.config["worker"]["url"].split("/")
        if "username" in self.config["worker"] and "password" in self.config["worker"] and \
                self.config["worker"]["username"] is not None and \
                self.config["worker"]["password"] is not None:
            
            git_url = f'''{"/".join(url[ : url.index("") + 1])}/
                          {self.config["worker"]["username"]}:{self.config["worker"]["password"]}
                          @{"/".join(url[url.index("") + 1 : ])}'''
            git_url = git_url.replace("\n", "").replace("\t", "").replace(" ", "")
        else:
            git_url = self.config["worker"]["url"]
        
        Repo.clone_from(git_url, worker_path)
