import importlib
import asyncio
import logging
import shutil
import os
import pip
from git.repo import Repo
from fatcat_utils.rabbitmq import RabbitMQHandler, RABBIT_CONFIG
from fatcat_utils.mongodb import DatabaseHandler
from fatcat_utils.logger import generate_logger
from .config import load_config, IConfig


RABBIT_CONFIG["failed_queue"] = os.getenv("FATCAT_RABBIT_WORKER_FAILED_QUEUE", "worker-failed")

class Worker:
    """Worker class.

    Nothing much to document really. Just a class with all the worker functions
    """
    logger: logging.Logger = generate_logger(f"FatCatWorker{os.getenv('FATCAT_WORKER_NAME')}Logger")
    rabbit: RabbitMQHandler = RabbitMQHandler()
    mongo: DatabaseHandler = DatabaseHandler()
    config: IConfig = load_config()

    def run(self):
        """The run function.

        Call this function to start the worker.
        """
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.start())
        loop.call_later(5, self.check_listeners_status)
        loop.run_forever()

    async def start(self):
        """THe start function.
        
        Sets up the mongo, clones the worker repo, 
        initiates the listeners and connectes to the rabbit
        """
        self.logger.info("Setting up the Mongo environment")
        await self.mongo.setup()
        self.logger.info("Mongo has been set up")

        self.logger.info("Inserting queues and schemas to the database")
        await self.insert_queues_to_database()
        self.logger.info("Finished inserting queues and schemas to the database")

        if "url" in self.config["worker"]:
            self.logger.info("Cloning the worker from Git")
            self.clone_worker()
            self.logger.info("Done with the cloning")
        elif "path" in self.config["worker"]:
            self.logger.debug("Checking if worker exists")
            if not (os.path.exists(self.config["worker"]["path"]) and os.path.isdir(self.config["worker"]["path"])):
                self.logger.error(f"Worker path {self.config['worker']['path']} doesn't exist")
            self.logger.debug("Worker path exists")
        else:
            self.logger.error("Key error in worker configuration")

        self.logger.info("Installing worker dependencies")
        self.install_worker_deps()
        self.logger.info("Done installing worker dependencies")

        self.logger.info("Loading the worker")
        await self.load_worker()
        self.logger.info("Done loading the worker")

        self.logger.info("Starting up the Rabbit handler")
        await self.rabbit.connect()
        self.logger.info("Rabbit handler was been connected")

    async def insert_queues_to_database(self):
        """Inserts the queues from the configuration to the database
        """
        for queue in self.config["queues"]:
            self.logger.debug("Checking if queue document exists")
            queue_doc = await self.mongo.get_queue_based_on_name(queue["queue_name"])

            if queue_doc is None or queue_doc == {}:
                self.logger.debug("Queue document doesn't exist. Creating new queue and schemas")
                await self.mongo.create_queue({
                    "queue_name": queue["queue_name"],
                    "tags": queue["tags"]
                }, queue["schemas"] if "schemas" in queue else None)
            else:
                self.logger.debug("Queue document exists. Updating it")
                await self.mongo.update_queue({
                    "queue_name": queue["queue_name"], "tags": queue["tags"]
                })
                self.logger.debug("Updating schemas in the database")
                await self.mongo.update_schema(queue["schemas"] if "schemas" in queue else None, queue["queue_name"])

    async def load_worker(self):
        """Loads the worker from the folder
        """
        self.logger.debug("Loading the worker")
        worker = importlib.import_module("worker", os.getcwd())

        load_worker = getattr(worker, "setup_worker")
        if asyncio.coroutines.iscoroutinefunction(worker):
            self.logger.debug("Worker's setup function is a coroutine. Awaiting it")
            await load_worker()
        else:
            self.logger.debug("Worker's setup function is a normal function (probably). Calling it")
            load_worker()
    
    def install_worker_deps(self):
        """Installing the worker dependencies (if exists)
        """
        if os.path.exists(os.path.join(os.getcwd(), "worker", "requirements.txt")) and not os.path.isdir(os.path.join(os.getcwd(), "worker", "requirements.txt")):
            self.logger.debug("Installing worker dependencies")
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
        self.logger.debug("Checking if the worker path exists")
        worker_path = os.path.join(os.getcwd(), "worker")
        if not os.path.exists(worker_path):
            self.logger.debug("Worker path doesn't exist. Creating it")
            os.mkdir(worker_path)
        elif os.getenv("FATCAT_FORCE_GIT", "1") == "0": 
            self.logger.debug("Worker path exists and I was asked not to clean. Exiting function")
            #  Continuing if it exists (this way you can just use it without git)
            return 
        else:
            self.logger.debug("Worker path exists. Deleting it and recreating it")
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

    def check_listeners_status(self):
        """Checks if there are any active listeners. If not, kills the program.
        """
        loop = asyncio.get_event_loop()
        self.logger.debug("Checking if there are no active listeners")
        if len(self.rabbit._background_listeners) == 0:
            self.logger.debug("No active listeners. Closing RabbitMQ and the async loop.")
            loop.call_later(0.1, self.rabbit.close)  # Doesn't work with loop.run_until_complete cause of loop.run_forever
            loop.stop()
        else:
            loop.call_later(5, self.check_listeners_status)
